"""
transactions/services.py — ImportService: writes parsed transactions to the database.

Why a service layer?
--------------------
The management commands (import_yuh, import_ubs, import_cic) handle:
    - Loading the file
    - Detecting the format (which connector to use)
    - Resolving the account (IBAN match, bank slug convention...)
    - Printing a user-facing report

The ImportService handles:
    - Deduplication (import_hash already in DB?)
    - Card resolution (last_four → Card object)
    - Auto-categorisation (CategorizationRule keyword matching)
    - Writing Transaction rows to the database
    - Creating a BalanceSnapshot (if balance is provided)
    - Creating an ImportLog (audit trail: what was imported, when, by whom)

This separation means the same service can later be called from:
    - A web upload form (Phase 6 UI)
    - A background task (Django-Q watcher)
    - A management command (today)

No command-specific printing here — only business logic and DB writes.
"""

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import time as time_type
from decimal import Decimal
from pathlib import Path

from django.db import transaction as db_transaction

from accounts.models import Account, BalanceSnapshot, Card, ExchangeRate
from connectors.base import TransactionDict
from transactions.models import CategorizationRule, ImportLog, Transaction

# =============================================================================
# ImportResult — returned by ImportService.run()
# =============================================================================


@dataclass
class ImportResult:
    """
    Summary of what happened during an import run.

    Returned by ImportService.run() so the caller (management command, view...)
    can decide how to display the outcome without coupling to DB logic.

    Using @dataclass gives us a clean container with default values and
    free __repr__ for debugging — no boilerplate constructor needed.
    """

    count_created: int = 0  # new transactions inserted into the DB
    count_skipped: int = 0  # duplicates (import_hash already in DB)
    count_errors: int = 0  # rows that couldn't be processed
    error_detail: list[str] = field(default_factory=list)  # one message per error


# =============================================================================
# File hash helper
# =============================================================================


def compute_file_hash(filepath: Path) -> str:
    """
    Compute the SHA1 hash of a file's raw content.

    Used to detect if the exact same file was already imported.
    Stored in ImportLog.file_hash (unique=True in DB).

    Why SHA1?
    - Same choice as import_hash (per-row deduplication in connectors)
    - SHA1 is fast, and we're not using it for security — just equality checks
    - 40-char hex fits our CharField(max_length=40)

    Why read in 64KB chunks?
    - Avoids loading the entire file into memory — safe for large Excel files
    """
    sha1 = hashlib.sha1()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha1.update(chunk)
    return sha1.hexdigest()


# =============================================================================
# get_exchange_rate — Récupère le taux de change via DB ou frankfurter.app
# =============================================================================


def get_exchange_rate(
    date: date_type, from_currency: str, to_currency: str = "CHF"
) -> Decimal | None:
    """
    Retourne le taux de change from_currency → to_currency pour une date donnée.

    Stratégie : DB d'abord, API ensuite.
        1. Si le taux existe déjà dans ExchangeRate → le retourner directement.
           (Évite un appel réseau à chaque transaction — un import CIC de 200 lignes
           ne fera que quelques appels API, les dates se répétant souvent.)
        2. Si absent → appeler frankfurter.app (API publique, gratuite, pas de clé).
        3. Stocker le résultat dans ExchangeRate pour les appels futurs.
        4. En cas d'erreur réseau ou API → retourner None sans crasher l'import.

    Pourquoi NOT get_or_create ?
        get_or_create passerait le rate=None à la création, puis on devrait le mettre
        à jour. Deux requêtes au lieu d'une. Plus simple : get() → None → appel API
        → create().

    API frankfurter.app — exemple :
        GET https://api.frankfurter.app/2026-03-17?from=EUR&to=CHF
        → {"amount":1.0,"base":"EUR","date":"2026-03-17","rates":{"CHF":0.9321}}

    ⚠️  NOUVEAU CONNECTEUR (devise non-CHF) :
        Si tu ajoutes un compte GBP, CAD, USD... → cette fonction le gère automatiquement.
        frankfurter.app supporte toutes les devises majeures.
        Vérifier que la devise est supportée : https://api.frankfurter.app/currencies
    """
    if from_currency == to_currency:
        return Decimal("1")

    # ── 1. DB d'abord ────────────────────────────────────────────────────────
    try:
        existing = ExchangeRate.objects.get(
            date=date, from_currency=from_currency, to_currency=to_currency
        )
        return existing.rate
    except ExchangeRate.DoesNotExist:
        pass  # pas encore en cache → appel API ci-dessous

    # ── 2. Appel API frankfurter.app ─────────────────────────────────────────
    date_str = date.isoformat()  # "2026-03-17"
    url = (
        f"https://api.frankfurter.app/{date_str}?from={from_currency}&to={to_currency}"
    )

    try:
        # frankfurter.app bloque les requêtes sans User-Agent (répond 403).
        # On ajoute un header minimal pour identifier notre client.
        req = urllib.request.Request(url, headers={"User-Agent": "BricBudget/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            rate = Decimal(str(data["rates"][to_currency]))
    except (urllib.error.URLError, KeyError, ValueError) as e:
        # Erreur réseau ou format inattendu → on ne plante pas l'import.
        # La transaction sera créée avec amount_chf=None — mieux que de tout perdre.
        print(
            f"[exchange_rate] WARNING: could not fetch {from_currency}→{to_currency} for {date_str}: {e}"
        )
        return None

    # ── 3. Stocker en DB pour les prochains imports ───────────────────────────
    ExchangeRate.objects.create(
        date=date,
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
    )

    return rate


# =============================================================================
# ImportService
# =============================================================================


class ImportService:
    """
    Orchestrates writing a batch of parsed transactions into the database.

    Call ImportService().run(...) from a management command or a view.
    The service is stateless — no __init__ needed, no instance variables.

    dry_run=True lets you preview what would happen without touching the DB.
    This keeps the management command's dry-run mode working after Phase 1A.
    """

    def run(
        self,
        transactions: list[TransactionDict],
        account: Account,
        imported_by,  # settings.AUTH_USER_MODEL instance (CustomUser)
        filename: str,
        file_hash: str,
        balance: float | None = None,
        dry_run: bool = False,
    ) -> ImportResult:
        """
        Main entry point. Process a list of TransactionDicts for one account.

        Steps:
            1. Guard: reject if this exact file was already imported
            2. Load existing import_hashes (one DB query — avoids per-row queries)
            3. Load categorization rules (one DB query)
            4. Build card map (one DB query)
            5. Loop: build Transaction objects, skipping duplicates
            6. Write: bulk insert + BalanceSnapshot + ImportLog (all in one transaction)

        If dry_run=True, steps 1-5 run normally but step 6 is skipped.
        Returns an ImportResult with counts in both cases.
        """
        result = ImportResult()

        # ── 1. File-level deduplication ───────────────────────────────────────
        # If this exact file was already imported, abort immediately.
        # ImportLog.file_hash is unique=True — importing twice would raise IntegrityError
        # at the DB level anyway, but we want a clean error message, not a crash.
        if ImportLog.objects.filter(file_hash=file_hash).exists():
            result.count_errors = 1
            result.error_detail.append(
                f"File '{filename}' was already imported (file_hash match). "
                "Nothing was written."
            )
            return result

        # ── 2. Load existing hashes for this batch (one query) ───────────────
        # import_hash is unique across the ENTIRE transactions table (not per account).
        # Filtering by account would miss transactions previously imported against
        # a different account ID (e.g. after a reset-seed that recreated accounts).
        #
        # Instead: only fetch hashes that are actually in this batch — fast and precise.
        # For 226 transactions that's 226 SHA1 strings (~9KB) — negligible.
        incoming_hashes = [tx["import_hash"] for tx in transactions]
        existing_hashes = set(
            Transaction.objects.filter(import_hash__in=incoming_hashes).values_list(
                "import_hash", flat=True
            )
        )

        # ── 3. Load categorization rules (one query, sorted by priority) ──────
        # All rules loaded upfront to avoid per-row DB queries.
        # select_related("category", "subcategory") fetches them in the same query —
        # otherwise each rule access would trigger a separate SQL SELECT (N+1 problem).
        rules = list(
            CategorizationRule.objects.filter(is_active=True)
            .select_related("category", "subcategory")
            .order_by("-priority")
        )

        # ── 4. Build card map for this account (one query) ───────────────────
        # {last_four: Card} — lets us resolve "8703" → Card object in O(1).
        # Savings accounts have no checking_account → returns {} (no cards).
        cards_by_last_four = self._load_cards(account)

        # ── 5. Process each transaction ───────────────────────────────────────
        transactions_to_create = []

        for tx in transactions:
            # Duplicate check: this hash already exists in the DB → skip silently
            if tx["import_hash"] in existing_hashes:
                result.count_skipped += 1
                continue

            try:
                obj = self._build_transaction(tx, account, cards_by_last_four, rules)
                transactions_to_create.append(obj)
            except Exception as e:
                # Log the error but keep processing — a bad row shouldn't block the rest
                result.count_errors += 1
                result.error_detail.append(
                    f"Row {tx.get('date')} | {tx.get('description_raw', '')[:60]}: {e}"
                )

        result.count_created = len(transactions_to_create)

        # ── 6. Dry run: stop here, return counts ──────────────────────────────
        # The caller (management command) can print the result without any DB writes.
        if dry_run:
            return result

        # ── 7. Write to DB — all in one atomic transaction ───────────────────
        # db_transaction.atomic() is a context manager that wraps all writes in
        # a single SQL transaction. If anything inside raises an exception,
        # PostgreSQL rolls back ALL writes — no partial imports.
        # "Atomic" = either everything succeeds, or nothing changes.
        with db_transaction.atomic():
            # bulk_create: one SQL INSERT for all new transactions instead of one per row.
            # ignore_conflicts=False (default): if a hash slips through the duplicate
            # check above (rare race condition), let it raise so we notice.
            if transactions_to_create:
                Transaction.objects.bulk_create(transactions_to_create)

            # BalanceSnapshot: record the account balance at the time of export.
            # update_or_create: safe to re-run — won't duplicate if same (account, date).
            if balance is not None and transactions_to_create:
                # Use the most recent transaction date as the snapshot date.
                # For Yuh the balance is "current" — matches the export date
                # which is also the date of the most recent transaction.
                snapshot_date = max(t.date for t in transactions_to_create)

                # For CHF accounts, balance_chf = balance directly.
                # For EUR/GBP accounts, we leave balance_chf=None until exchange
                # rates are loaded (Phase 1C — frankfurter.app integration).
                balance_chf = (
                    Decimal(str(balance)) if account.currency == "CHF" else None
                )

                BalanceSnapshot.objects.update_or_create(
                    account=account,
                    date=snapshot_date,
                    defaults={
                        "balance": Decimal(str(balance)),
                        "currency": account.currency,
                        "balance_chf": balance_chf,
                        "source": BalanceSnapshot.Source.IMPORT,
                    },
                )

            # ImportLog: audit trail — one row per import session.
            # Answers "what file was imported, when, by whom, with what result?"
            if result.count_errors == 0:
                status = ImportLog.Status.SUCCESS
            elif result.count_created > 0:
                status = ImportLog.Status.PARTIAL  # some rows worked, some didn't
            else:
                status = ImportLog.Status.FAILED  # nothing was created

            ImportLog.objects.create(
                account=account,
                imported_by=imported_by,
                filename=filename,
                file_hash=file_hash,
                status=status,
                count_created=result.count_created,
                count_skipped=result.count_skipped,
                count_errors=result.count_errors,
                error_detail="\n".join(result.error_detail),
            )

        return result

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _load_cards(self, account: Account) -> dict:
        """
        Return {last_four: Card} for all active cards on this account.

        Checks if the account has a CheckingAccount first — savings accounts
        don't have cards, and querying checking_account__account on a savings
        account would return an empty queryset (no error, but pointless).

        Returns an empty dict for savings accounts and accounts with no cards.
        """
        try:
            return {
                card.last_four: card
                for card in Card.objects.filter(
                    checking_account__account=account,
                    is_active=True,
                ).select_related("user")
            }
        except Exception:
            # Should never happen, but never crash an import for card resolution
            return {}

    def _build_transaction(
        self,
        tx: TransactionDict,
        account: Account,
        cards_by_last_four: dict,
        rules: list,
    ) -> Transaction:
        """
        Build a Transaction model instance from a TransactionDict.

        Does NOT save to the database — just creates the Python object.
        bulk_create() in run() handles the actual INSERT.

        Handles:
        - Type conversions (str → date, str → time, float → Decimal)
        - Card resolution (last_four → Card object or None)
        - Auto-categorisation (first matching rule wins)
        - amount_chf: set if currency is CHF, left None otherwise (Phase 1C)
        """
        # --- Type conversions ------------------------------------------------
        # TransactionDict.date is a string "YYYY-MM-DD" (ISO 8601).
        # Transaction.date is a Django DateField — it accepts strings, but being
        # explicit with date_type.fromisoformat() avoids silent format mismatches.
        parsed_date = date_type.fromisoformat(tx["date"])

        # time is optional — UBS provides it ("12:36:26"), Yuh/CIC don't.
        parsed_time = None
        if tx.get("time"):
            parsed_time = time_type.fromisoformat(tx["time"])

        # float → Decimal for monetary precision.
        # str(float) avoids floating-point representation issues:
        # Decimal(9.99) can give Decimal('9.98999...') — Decimal("9.99") is exact.
        amount = Decimal(str(tx["amount"]))

        # --- Card resolution -------------------------------------------------
        # card_last_four can be None (salary, bank transfer...) or a 4-digit string.
        card = None
        if tx.get("card_last_four"):
            card = cards_by_last_four.get(tx["card_last_four"])
            # card is None here = card seen in file but not in DB
            # (e.g. a card not yet seeded). Transaction is still created — card=NULL.

        # --- Categorisation --------------------------------------------------
        matched_rule = self._find_rule(tx, rules)

        if matched_rule:
            category = matched_rule.category
            subcategory = matched_rule.subcategory
            # Pre-fill nature from the sub-category's default, if available.
            # The user can override it later per-transaction in the UI.
            nature = subcategory.default_nature if subcategory else ""
            categorization_source = Transaction.CategorizationSource.RULE
        else:
            # No rule matched → category=None (shown as "Unknown" in UI queries)
            category = None
            subcategory = None
            nature = ""
            categorization_source = Transaction.CategorizationSource.DEFAULT

        # --- amount_chf ------------------------------------------------------
        # For CHF accounts: amount_chf = amount (no conversion needed).
        # For other currencies: fetch the rate from DB or frankfurter.app API,
        # then multiply. If the API fails, amount_chf stays None — the import
        # continues, and the field can be backfilled later.
        if account.currency == "CHF":
            amount_chf = amount
        else:
            rate = get_exchange_rate(parsed_date, account.currency)
            if rate is not None:
                # Quantize to 2 decimal places — same precision as amount
                amount_chf = (amount * rate).quantize(Decimal("0.01"))
            else:
                amount_chf = None

        # --- Build and return the unsaved object -----------------------------
        return Transaction(
            account=account,
            card=card,
            category=category,
            subcategory=subcategory,
            nature=nature,
            categorization_source=categorization_source,
            categorization_rule=matched_rule,
            date=parsed_date,
            time=parsed_time,
            amount=amount,
            currency=tx["currency"],
            amount_chf=amount_chf,
            description_raw=tx["description_raw"],
            merchant_name=tx["merchant_name"],
            # note, is_reconciled, is_ignored, is_recurring, is_internal_transfer:
            # all left at their model defaults (blank / False) — user fills them later
            import_hash=tx["import_hash"],
        )

    def _find_rule(self, tx: TransactionDict, rules: list) -> CategorizationRule | None:
        """
        Find the first categorisation rule whose keyword matches this transaction.

        Rules are already sorted by descending priority (highest first).
        We return on the first match — highest-priority rule wins.

        Matching is case-insensitive substring search:
            rule.keyword = "migros" matches "MIGROS LAUSANNE" → True
            rule.keyword = "migros" matches "DEMIGROS" → True (intentional — simpler)

        target_field determines which transaction field to search:
            "merchant_name"   → the cleaned display name (default)
            "description_raw" → the unmodified bank text (for tricky patterns)

        Returns None if no rule matches → caller sets category=None ("Unknown").
        """
        for rule in rules:
            if rule.target_field == CategorizationRule.TargetField.MERCHANT_NAME:
                text = tx["merchant_name"]
            else:
                text = tx["description_raw"]

            if rule.keyword.lower() in text.lower():
                return rule

        return None

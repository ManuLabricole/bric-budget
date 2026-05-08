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

import datetime as _dt
import hashlib
import json
import logging
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
from transactions.models import CategorizationRule, Category, ImportLog, Transaction

logger = logging.getLogger(__name__)

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

    # PK de l'ImportLog créé lors de l'écriture en DB.
    # None si dry_run=True (pas d'écriture) ou si une erreur précoce a bloqué
    # la création du log (ex: fichier déjà importé → return early).
    # Utilisé par import_confirm pour retrouver les transactions insérées et
    # déclencher le stockage permanent du fichier source.
    log_pk: int | None = None


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
        logger.warning(
            "exchange_rate: could not fetch %s→%s for %s: %s",
            from_currency,
            to_currency,
            date_str,
            e,
        )
        return None

    # ── 3. Stocker en DB pour les prochains imports ───────────────────────────
    # get_or_create évite une IntegrityError si deux imports simultanés appellent
    # cette fonction pour la même date/devise en même temps (race condition).
    ExchangeRate.objects.get_or_create(
        date=date,
        from_currency=from_currency,
        to_currency=to_currency,
        defaults={"rate": rate},
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

        # ── 3. Load categorization rules + default categories (one query each) ──
        rules = list(
            CategorizationRule.objects.filter(is_active=True)
            .select_related("category", "subcategory")
            .order_by("-priority")
        )
        # Default categories when no rule matches — loaded once, used per row.
        # get() returns None if the category doesn't exist yet (DB not seeded).
        default_income_category = Category.objects.filter(slug="revenus").first()
        default_unknown_category = Category.objects.filter(slug="inconnu").first()

        # ── 4. Build card map for this account (one query) ───────────────────
        # {last_four: Card} — lets us resolve "8703" → Card object in O(1).
        # Savings accounts have no checking_account → returns {} (no cards).
        cards_by_last_four = self._load_cards(account)

        # ── 5. Extract daily end-of-day balances from balance_after ──────────
        # Populated only for CIC (column F — Solde après transaction).
        # Yuh and UBS always return balance_after=None, so this dict stays empty
        # and has no effect on those connectors.
        #
        # CIC exports antichronologically (newest first) → the FIRST tx_dict seen
        # for a given date is the chronologically LAST transaction of that day
        # → its balance_after is the end-of-day balance. "first seen wins" gives
        # the correct end-of-day value for each date without any sorting.
        #
        # We scan the FULL transactions list (not just new ones) because
        # balance_after is authoritative bank data regardless of dedup status.
        daily_balances: dict[str, Decimal] = {}
        for _tx in transactions:
            _ba = _tx.get("balance_after")
            if _ba is not None and _tx["date"] not in daily_balances:
                daily_balances[_tx["date"]] = Decimal(str(_ba))

        # ── 6. Process each transaction ───────────────────────────────────────
        transactions_to_create = []
        # Garde trace des hashes vus dans CE batch pour dédupliquer les doublons
        # internes au fichier (ex: deux virements UBS identiques le même jour).
        # Sans ça, bulk_create lève une IntegrityError sur la contrainte unique import_hash.
        seen_in_batch = set()

        for tx in transactions:
            # Duplicate check contre la DB
            if tx["import_hash"] in existing_hashes:
                result.count_skipped += 1
                continue
            # Duplicate check au sein du fichier courant
            if tx["import_hash"] in seen_in_batch:
                result.count_skipped += 1
                continue
            seen_in_batch.add(tx["import_hash"])

            try:
                obj = self._build_transaction(
                    tx,
                    account,
                    cards_by_last_four,
                    rules,
                    default_income_category=default_income_category,
                    default_unknown_category=default_unknown_category,
                )
                transactions_to_create.append(obj)
            except Exception as e:
                # Log the error but keep processing — a bad row shouldn't block the rest
                result.count_errors += 1
                result.error_detail.append(
                    f"Row {tx.get('date')} | {tx.get('description_raw', '')[:60]}: {e}"
                )

        result.count_created = len(transactions_to_create)

        # ── 7. Dry run: stop here, return counts ──────────────────────────────
        # The caller (management command) can print the result without any DB writes.
        if dry_run:
            return result

        # ── 8. Write to DB — all in one atomic transaction ───────────────────
        # db_transaction.atomic() is a context manager that wraps all writes in
        # a single SQL transaction. If anything inside raises an exception,
        # PostgreSQL rolls back ALL writes — no partial imports.
        # "Atomic" = either everything succeeds, or nothing changes.
        with db_transaction.atomic():
            # ImportLog créé EN PREMIER pour pouvoir lier chaque transaction via FK.
            # On crée le log avant bulk_create pour avoir son pk disponible.
            if result.count_errors == 0:
                status = ImportLog.Status.SUCCESS
            elif result.count_created > 0:
                status = ImportLog.Status.PARTIAL
            else:
                status = ImportLog.Status.FAILED

            import_log = ImportLog.objects.create(
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

            # Lier chaque transaction à l'import qui la crée.
            # Ce FK permet de supprimer toutes les transactions d'un import d'un coup.
            for t in transactions_to_create:
                t.import_log = import_log

            if transactions_to_create:
                Transaction.objects.bulk_create(transactions_to_create)
                # Persist the transaction date range on the ImportLog for display.
                dates = [t.date for t in transactions_to_create]
                ImportLog.objects.filter(pk=import_log.pk).update(
                    date_min=min(dates),
                    date_max=max(dates),
                )

            # ── Daily BalanceSnapshots from per-row balance_after (CIC only) ──
            # For each date in the file where the bank provides a running balance,
            # we persist an end-of-day BalanceSnapshot. This builds a full balance
            # history curve (one point per day) rather than a single closing value.
            #
            # update_or_create: safe on re-import of overlapping date ranges.
            # We do NOT touch computed_balance here — that's managed by the
            # single-snapshot block below (which adds the "derived" running total).
            #
            # Guard: only run if there are new transactions. If all transactions
            # are duplicates (skipped), we skip snapshot creation too — a pure-
            # duplicate import shouldn't silently update balance history.
            if daily_balances and transactions_to_create:
                for _snap_date_str, _snap_balance in daily_balances.items():
                    BalanceSnapshot.objects.update_or_create(
                        account=account,
                        date=_dt.date.fromisoformat(_snap_date_str),
                        defaults={
                            "balance": _snap_balance,
                            "currency": account.currency,
                            "balance_chf": _snap_balance
                            if account.currency == "CHF"
                            else None,
                            "source": BalanceSnapshot.Source.IMPORT,
                        },
                    )

            # BalanceSnapshot : enregistre le solde du compte à la date d'export.
            # update_or_create : safe à ré-exécuter — pas de doublon si (account, date) identique.
            #
            # Deux valeurs complémentaires :
            #   balance          = solde extrait du fichier (None si le connecteur ne peut pas)
            #   computed_balance = snapshot précédent + somme des nouvelles transactions
            #
            # Même si balance=None (ex: Yuh avec nom de fichier URL-encodé), on crée quand même
            # le snapshot avec computed_balance pour ne pas perdre la traçabilité.
            # Si les deux sont disponibles, on vérifie la dérive pour détecter des anomalies.
            if transactions_to_create:
                snapshot_date = max(t.date for t in transactions_to_create)

                # Calculer computed_balance à partir du snapshot précédent.
                # IMPORTANT : date__lt=snapshot_date filtre UNIQUEMENT les snapshots
                # antérieurs à la date qu'on insère. Sans ce filtre, un import
                # rétroactif (ex : fichier CIC de janvier importé en mai) prendrait
                # le snapshot le plus récent en DB comme base, ce qui donne un
                # computed_balance complètement faux.
                prev = (
                    BalanceSnapshot.objects.filter(
                        account=account, date__lt=snapshot_date
                    )
                    .order_by("-date")
                    .first()
                )
                if prev is not None:
                    prev_bal = (
                        prev.balance
                        if prev.balance is not None
                        else prev.computed_balance
                    )
                    if prev_bal is not None:
                        computed = prev_bal + sum(
                            Decimal(str(t.amount)) for t in transactions_to_create
                        )
                    else:
                        computed = None
                else:
                    # Premier import pour ce compte : pas de base de calcul
                    computed = None

                # For CHF accounts, balance_chf = balance directly.
                # For EUR/GBP accounts, we leave balance_chf=None until exchange
                # rates are loaded (Phase 1C — frankfurter.app integration).
                extracted = Decimal(str(balance)) if balance is not None else None
                balance_chf = extracted if account.currency == "CHF" else None

                if extracted is not None or computed is not None:
                    # Build defaults carefully: never overwrite an existing
                    # bank-provided balance with None.
                    # This matters for CIC: the daily loop above may have already
                    # written balance for snapshot_date (from balance_after col F).
                    # If footer extraction failed (extracted=None), we don't want
                    # to erase that good value.
                    snap_defaults: dict = {
                        "currency": account.currency,
                        "source": BalanceSnapshot.Source.IMPORT,
                    }
                    if extracted is not None:
                        snap_defaults["balance"] = extracted
                        snap_defaults["balance_chf"] = balance_chf
                    if computed is not None:
                        snap_defaults["computed_balance"] = computed

                    BalanceSnapshot.objects.update_or_create(
                        account=account,
                        date=snapshot_date,
                        defaults=snap_defaults,
                    )

                # Alerte si les deux sont disponibles et divergent de plus de 1 centime
                if extracted is not None and computed is not None:
                    import logging

                    _log = logging.getLogger(__name__)
                    drift = abs(extracted - computed)
                    if drift > Decimal("0.01"):
                        _log.warning(
                            "Balance drift %.2f %s on account '%s' "
                            "(extracted=%.2f, computed=%.2f)",
                            drift,
                            account.currency,
                            account.name,
                            extracted,
                            computed,
                        )

            # Exposer le PK de l'ImportLog au caller (views.py) pour pouvoir
            # retrouver les transactions insérées et déclencher le stockage du fichier.
            result.log_pk = import_log.pk

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
        default_income_category=None,
        default_unknown_category=None,
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
            # No rule matched — assign default category based on sign of amount:
            #   positive (income)  → "income" category
            #   negative (expense) → "unknown" category
            subcategory = None
            nature = ""
            categorization_source = Transaction.CategorizationSource.DEFAULT
            amount = Decimal(str(tx.get("amount", 0)))
            if amount >= 0:
                category = default_income_category  # None if not seeded yet
            else:
                category = default_unknown_category  # None if not seeded yet

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
            display_name=tx["display_name"],
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
            "display_name"    → the stored clean bank-agnostic name (canonical since Phase 2G)
            "merchant_name"   → legacy alias for display_name (same value at import time)
            "description_raw" → the unmodified bank text (kept for backward compat with old rules)

        Returns None if no rule matches → caller sets category=None ("Unknown").
        """
        for rule in rules:
            if rule.target_field == CategorizationRule.TargetField.DESCRIPTION_RAW:
                text = tx["description_raw"]
            else:
                # display_name and merchant_name (legacy) both map to the clean name.
                text = tx["display_name"]

            if rule.keyword.lower() in text.lower():
                return rule

        return None

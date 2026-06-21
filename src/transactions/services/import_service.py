"""
transactions/services/import_service.py — ImportService: writes parsed transactions to DB.

Découpé du fichier services.py en package (#183) : get_exchange_rate vit désormais
dans services/exchange_rates.py ; compute_file_hash → file_hash.py ;
sync_internal_transfer + INTERNAL_TRANSFER_SLUG → internal_transfer.py.

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
import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import time as time_type
from decimal import Decimal

from django.db import transaction as db_transaction

from accounts.models import Account, BalanceSnapshot, Card
from connectors.base import TransactionDict
from services.exchange_rates import get_exchange_rate
from transactions.models import CategorizationRule, Category, ImportLog, Transaction

from .internal_transfer import INTERNAL_TRANSFER_SLUG

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

        # ── 1. Garde anti-doublon fichier (return early) ─────────────────────
        if self._already_imported(file_hash, account):
            result.count_errors = 1
            result.error_detail.append(
                f"File '{filename}' was already imported (file_hash match). "
                "Nothing was written."
            )
            return result

        # ── 2. Lookups (une requête chacun, réutilisés par ligne) ────────────
        existing_hashes = self._load_existing_hashes(transactions)
        rules = self._load_rules()
        default_income_category, default_unknown_category = (
            self._load_default_categories()
        )
        cards_by_last_four = self._load_cards(account)

        # ── 3. Soldes quotidiens fin de journée depuis balance_after (CIC) ───
        daily_balances = self._extract_daily_balances(transactions)

        # ── 4. Construire les transactions (dédup DB + intra-fichier) ────────
        transactions_to_create = self._build_transactions(
            transactions,
            account,
            cards_by_last_four,
            rules,
            default_income_category,
            default_unknown_category,
            existing_hashes,
            result,
        )
        result.count_created = len(transactions_to_create)

        # ── 5. Dry run : on s'arrête avant toute écriture ────────────────────
        # Le caller (management command) peut afficher le result sans écrire en DB.
        if dry_run:
            return result

        # ── 6. Écriture atomique (ImportLog + transactions + snapshots) ──────
        self._persist(
            account=account,
            imported_by=imported_by,
            filename=filename,
            file_hash=file_hash,
            transactions_to_create=transactions_to_create,
            daily_balances=daily_balances,
            balance=balance,
            result=result,
        )

        return result

    # =========================================================================
    # Private helpers — phases de run() (#183)
    # =========================================================================

    def _already_imported(self, file_hash: str, account: Account) -> bool:
        """True si ce fichier exact a déjà été importé pour CE compte.

        Scopé au compte : deux users peuvent importer le même fichier dans
        leurs propres comptes sans collision.
        """
        return ImportLog.objects.filter(file_hash=file_hash, account=account).exists()

    def _load_existing_hashes(self, transactions: list[TransactionDict]) -> set[str]:
        """Hashes déjà en DB pour CE batch (une requête).

        import_hash est unique sur TOUTE la table (pas par compte). Filtrer par
        compte raterait des transactions importées sous un autre ID de compte
        (ex: après un reset-seed qui recrée les comptes). On ne récupère donc que
        les hashes présents dans le batch — rapide et précis. Pour 226
        transactions = 226 chaînes SHA1 (~9KB), négligeable.
        """
        incoming_hashes = [tx["import_hash"] for tx in transactions]
        return set(
            Transaction.objects.filter(import_hash__in=incoming_hashes).values_list(
                "import_hash", flat=True
            )
        )

    def _load_rules(self) -> list[CategorizationRule]:
        """Règles actives triées par priorité décroissante (une requête)."""
        return list(
            CategorizationRule.objects.filter(is_active=True)
            .select_related("category", "subcategory")
            .order_by("-priority")
        )

    def _load_default_categories(self) -> tuple[Category | None, Category | None]:
        """Catégories par défaut (revenus / inconnu) quand aucune règle ne matche.

        first() retourne None si la catégorie n'existe pas encore (DB non seedée).
        """
        default_income_category = Category.objects.filter(slug="revenus").first()
        default_unknown_category = Category.objects.filter(slug="inconnu").first()
        return default_income_category, default_unknown_category

    def _extract_daily_balances(
        self, transactions: list[TransactionDict]
    ) -> dict[str, Decimal]:
        """Soldes fin de journée par date depuis balance_after (CIC uniquement).

        Yuh et UBS renvoient toujours balance_after=None → dict vide, sans effet.

        CIC exporte antichronologiquement (plus récent d'abord) → le PREMIER
        tx_dict vu pour une date est la dernière transaction chronologique du
        jour → son balance_after est le solde de fin de journée. "first seen
        wins" donne la bonne valeur sans tri.

        On scanne TOUTE la liste (pas seulement les nouvelles) car balance_after
        est une donnée banque faisant autorité quel que soit le statut de dédup.
        """
        daily_balances: dict[str, Decimal] = {}
        for _tx in transactions:
            _ba = _tx.get("balance_after")
            if _ba is not None and _tx["date"] not in daily_balances:
                daily_balances[_tx["date"]] = Decimal(str(_ba))
        return daily_balances

    def _build_transactions(
        self,
        transactions: list[TransactionDict],
        account: Account,
        cards_by_last_four: dict,
        rules: list,
        default_income_category,
        default_unknown_category,
        existing_hashes: set[str],
        result: ImportResult,
    ) -> list[Transaction]:
        """Construit les objets Transaction non sauvegardés, en sautant les doublons.

        Mute result.count_skipped / count_errors / error_detail au passage.
        Une ligne en erreur est loggée et sautée — elle ne bloque pas le reste.
        """
        transactions_to_create: list[Transaction] = []
        # Garde trace des hashes vus dans CE batch pour dédupliquer les doublons
        # internes au fichier (ex: deux virements UBS identiques le même jour).
        # Sans ça, bulk_create lève une IntegrityError sur la contrainte unique import_hash.
        seen_in_batch: set[str] = set()

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
                logger.warning(
                    "ImportService: row build failed (%s | %s): %s",
                    tx.get("date"),
                    tx.get("description_raw", "")[:60],
                    e,
                    exc_info=True,
                )
                result.count_errors += 1
                result.error_detail.append(
                    f"Row {tx.get('date')} | {tx.get('description_raw', '')[:60]}: {e}"
                )

        return transactions_to_create

    def _persist(
        self,
        *,
        account: Account,
        imported_by,
        filename: str,
        file_hash: str,
        transactions_to_create: list[Transaction],
        daily_balances: dict[str, Decimal],
        balance: float | None,
        result: ImportResult,
    ) -> None:
        """Écrit tout en UNE transaction atomique (SR-003) — tout ou rien.

        ImportLog créé EN PREMIER (pour lier les transactions via FK), puis
        bulk_create, puis les BalanceSnapshots. Expose result.log_pk au caller.
        """
        with db_transaction.atomic():
            import_log = self._create_import_log(
                account, imported_by, filename, file_hash, result
            )
            self._save_transactions(import_log, transactions_to_create)
            self._save_daily_snapshots(account, daily_balances, transactions_to_create)
            self._save_closing_snapshot(account, transactions_to_create, balance)
            # Exposer le PK de l'ImportLog au caller (orchestrator) pour retrouver
            # les transactions insérées et déclencher le stockage du fichier.
            result.log_pk = import_log.pk

    def _create_import_log(
        self,
        account: Account,
        imported_by,
        filename: str,
        file_hash: str,
        result: ImportResult,
    ) -> ImportLog:
        """Crée l'ImportLog — statut dérivé des compteurs du result."""
        if result.count_errors == 0:
            status = ImportLog.Status.SUCCESS
        elif result.count_created > 0:
            status = ImportLog.Status.PARTIAL
        else:
            status = ImportLog.Status.FAILED

        return ImportLog.objects.create(
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

    def _save_transactions(
        self, import_log: ImportLog, transactions_to_create: list[Transaction]
    ) -> None:
        """Lie chaque transaction à l'import puis bulk_create + plage de dates."""
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

    def _save_daily_snapshots(
        self,
        account: Account,
        daily_balances: dict[str, Decimal],
        transactions_to_create: list[Transaction],
    ) -> None:
        """BalanceSnapshots quotidiens depuis balance_after par ligne (CIC).

        Pour chaque date où la banque fournit un solde courant, on persiste un
        snapshot fin de journée → courbe complète (un point/jour) plutôt qu'une
        seule valeur de clôture. update_or_create : safe au ré-import de plages
        qui se chevauchent. On ne touche PAS computed_balance ici (géré par le
        snapshot de clôture).

        Garde : seulement s'il y a de NOUVELLES transactions. Si tout est en
        doublon (skipped), un import pur-doublon ne doit pas modifier
        silencieusement l'historique des soldes.
        """
        if not (daily_balances and transactions_to_create):
            return
        for _snap_date_str, _snap_balance in daily_balances.items():
            BalanceSnapshot.objects.update_or_create(
                account=account,
                date=_dt.date.fromisoformat(_snap_date_str),
                defaults={
                    "balance": _snap_balance,
                    "currency": account.currency,
                    "balance_chf": _snap_balance if account.currency == "CHF" else None,
                    "source": BalanceSnapshot.Source.IMPORT,
                },
            )

    def _save_closing_snapshot(
        self,
        account: Account,
        transactions_to_create: list[Transaction],
        balance: float | None,
    ) -> None:
        """BalanceSnapshot de clôture à la dernière date du batch.

        Deux valeurs complémentaires :
            balance          = solde extrait du fichier (None si indisponible)
            computed_balance = snapshot précédent + somme des nouvelles tx

        Même si balance=None (ex: Yuh nom de fichier URL-encodé), on crée quand
        même le snapshot avec computed_balance pour ne pas perdre la traçabilité.
        Si les deux sont disponibles, on alerte sur la dérive.
        """
        if not transactions_to_create:
            return

        snapshot_date = max(t.date for t in transactions_to_create)

        # date__lt=snapshot_date : base de calcul = snapshot ANTÉRIEUR uniquement.
        # Sans ce filtre, un import rétroactif (CIC de janvier importé en mai)
        # prendrait le snapshot le plus récent comme base → computed_balance faux.
        prev = (
            BalanceSnapshot.objects.filter(account=account, date__lt=snapshot_date)
            .order_by("-date")
            .first()
        )
        if prev is not None:
            prev_bal = (
                prev.balance if prev.balance is not None else prev.computed_balance
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

        # CHF : balance_chf = balance directement. EUR/GBP : None jusqu'au
        # chargement des taux (Phase 1C — frankfurter.app).
        extracted = Decimal(str(balance)) if balance is not None else None
        balance_chf = extracted if account.currency == "CHF" else None

        if extracted is not None or computed is not None:
            # Ne jamais écraser un solde banque existant par None. Important pour
            # CIC : la boucle quotidienne a pu déjà écrire balance pour cette date
            # (col F). Si l'extraction footer a échoué (extracted=None), on ne
            # veut pas effacer cette bonne valeur.
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
            drift = abs(extracted - computed)
            if drift > Decimal("0.01"):
                logger.warning(
                    "Balance drift %.2f %s on account '%s' "
                    "(extracted=%.2f, computed=%.2f)",
                    drift,
                    account.currency,
                    account.name,
                    extracted,
                    computed,
                )

    # =========================================================================
    # Private helpers — construction & catégorisation d'une transaction
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
            logger.exception("ImportService: card resolution unexpected failure")
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
        if raw_time := tx.get("time"):
            parsed_time = time_type.fromisoformat(raw_time)

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

        # --- Flags virement interne ------------------------------------------
        # Si la catégorie matchée est "virements", on marque la transaction comme
        # virement interne ET ignorée dès l'import. L'utilisateur peut overrider
        # manuellement via le toggle "Inclure dans l'analyse budgétaire".
        is_internal = bool(category and category.slug == INTERNAL_TRANSFER_SLUG)

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
            is_internal_transfer=is_internal,
            is_ignored=is_internal,
            import_hash=tx["import_hash"],
        )

    def _find_rule(
        self, tx: TransactionDict, rules: list[CategorizationRule]
    ) -> CategorizationRule | None:
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

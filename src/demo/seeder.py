"""
demo/seeder.py — construit une DB de démo (#118) VIA le vrai pipeline d'import.

seed_demo() : user démo (loginable, creds .env) → référentiels (institutions +
catégories) → comptes (IBAN/RIB synthétiques) → carte Yuh → pour chaque banque :
génère un fichier au format banque → prepare_import + run_import + persist_import_file
(= EXACTEMENT un upload web) → apply_rules. Résultat : ImportLog réels, transactions
liées à leur import, fichier chiffré stocké.

Fonctions PURES (pas de garde DEBUG ici) → testables. Le garde-fou
assert_dev_environment() vit sur les points d'entrée (commande dev_seed, panel admin).
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import transaction as db_transaction

from accounts.models import (
    Account,
    BalanceSnapshot,
    Card,
    CheckingAccount,
    ExchangeRate,
    Institution,
    SavingsAccount,
)
from budget.utils import seed_perso_categories
from demo import generators, profiles
from imports.orchestrator import persist_import_file, prepare_import, run_import
from services.exchange_rates import to_chf
from transactions.models import (
    CategorizationRule,
    Category,
    ImportLog,
    SubCategory,
    Transaction,
)

logger = logging.getLogger(__name__)


def _norm(identifier: str) -> str:
    """IBAN/RIB sans espaces = ce que le resolver matche (stocké espacé en source)."""
    return identifier.replace(" ", "")


@dataclass(frozen=True)
class _DemoAccount:
    """Un compte démo. iban (UBS) OU contract_number (CIC RIB) sert à la résolution
    d'import ; Yuh n'a aucun identifiant → résolu par forçage. currency CHF sauf CIC (EUR)."""

    key: str
    institution: str
    name: str
    account_type: str
    currency: str
    iban: str | None
    contract_number: str


@dataclass(frozen=True)
class _DemoFile:
    """Un fichier à importer. bank = clé generators.write_bank_file ; forced_account
    = clé de compte à forcer (Yuh, sans identifiant), None sinon (UBS→IBAN, CIC→RIB :
    1 .xlsx → 2 comptes résolus par RIB)."""

    bank: str
    fixture: str
    forced_account: str | None


# 3 banques × (courant + épargne) = 6 comptes.
_DEMO_ACCOUNTS = [
    _DemoAccount(
        "ubs_courant",
        "ubs",
        "UBS Compte courant",
        Account.AccountType.CHECKING,
        "CHF",
        _norm(profiles.DEMO_UBS_CHECKING_IBAN),
        "",
    ),
    _DemoAccount(
        "ubs_epargne",
        "ubs",
        "UBS Épargne",
        Account.AccountType.SAVINGS,
        "CHF",
        _norm(profiles.DEMO_UBS_SAVINGS_IBAN),
        "",
    ),
    _DemoAccount(
        "cic_courant",
        "cic",
        "CIC Compte courant",
        Account.AccountType.CHECKING,
        "EUR",
        None,
        _norm(generators.CIC_CHECKING_RIB),
    ),
    _DemoAccount(
        "cic_livret",
        "cic",
        "CIC Livret",
        Account.AccountType.SAVINGS,
        "EUR",
        None,
        _norm(generators.CIC_SAVINGS_RIB),
    ),
    _DemoAccount(
        "yuh_courant",
        "yuh",
        "Yuh Compte courant",
        Account.AccountType.CHECKING,
        "CHF",
        None,
        "",
    ),
    _DemoAccount(
        "yuh_epargne",
        "yuh",
        "Yuh Épargne",
        Account.AccountType.SAVINGS,
        "CHF",
        None,
        "",
    ),
]

# Fichiers importés. CIC = 1 .xlsx → 2 comptes (RIB). Yuh = 2 fichiers forcés
# (pas d'identifiant dans le CSV → on cible explicitement le bon compte).
_DEMO_FILES = [
    _DemoFile("ubs_checking", "ubs/ubs_checking_demo.csv", None),
    _DemoFile("ubs_savings", "ubs/ubs_savings_demo.csv", None),
    _DemoFile("cic", "cic/cic_demo.xlsx", None),
    _DemoFile("yuh", "yuh/yuh_demo.csv", "yuh_courant"),
    _DemoFile("yuh_savings", "yuh/yuh_savings_demo.csv", "yuh_epargne"),
]

FIXTURES_DIR = Path(settings.BASE_DIR) / "demo" / "fixtures"


@dataclass
class SeedSummary:
    user_email: str
    accounts: int
    rules: int
    imports: int
    created: int
    skipped: int


# ── API publique ──────────────────────────────────────────────────────────────


def seed_demo(
    *, flush: bool = False, months: int = 12, from_fixtures: bool = False
) -> SeedSummary:
    """Construit la DB de démo. Idempotent : re-run le même jour ne duplique rien
    (dédup file_hash). `flush` repart de zéro pour les comptes démo."""
    user = _ensure_demo_user()
    # Référentiels réels (idempotent) : institutions (ubs/yuh) + catégories
    # (revenus/inconnu pour la catégorisation par défaut à l'import).
    call_command("sync_reference_data")
    accounts = _ensure_accounts(user)
    # Règles AVANT les imports → la catégorisation se fait à l'import (ImportService).
    rules = _ensure_rules(user)
    # Catégories perso de démo : montre la feature ET re-prouve l'isolation inter-user.
    n_pcat, n_psub = seed_perso_categories(user, profiles.PERSO_CATEGORIES)
    logger.info("seed_demo perso: %d catégories + %d sous-catégories", n_pcat, n_psub)

    if flush:
        _flush_demo_data(list(accounts.values()))

    anchor = date.today()
    # EUR→CHF en DB AVANT l'import CIC → get_exchange_rate tape le cache, 0 réseau.
    _ensure_exchange_rates(anchor, months)
    imports = created = skipped = 0
    with tempfile.TemporaryDirectory(prefix="bric_demo_") as tmp:
        tmp_dir = Path(tmp)
        for spec in _DEMO_FILES:
            path = _resolve_file(
                spec, tmp_dir, months=months, anchor=anchor, from_fixtures=from_fixtures
            )
            # Yuh n'a pas d'identifiant dans le fichier → on force le bon compte.
            forced_id = (
                accounts[spec.forced_account].id if spec.forced_account else None
            )
            prepared = prepare_import(path, user=user, forced_account_id=forced_id)
            results = run_import(
                prepared, path, filename=path.name, imported_by=user, dry_run=False
            )
            persist_import_file(
                path=path,
                filename=path.name,
                matches=prepared.matches,
                balances=prepared.balances,
                results=results,
            )
            imports += sum(1 for r in results if r.log_pk)
            created += sum(r.count_created for r in results)
            skipped += sum(r.count_skipped for r in results)

    # Garantit un solde affichable par compte. UBS/CIC en ont déjà via l'import ;
    # Yuh n'expose pas de solde dans son CSV → sans ça il est INVISIBLE en patrimoine.
    _ensure_balances(list(accounts.values()))

    # Applique les règles de catégorisation existantes (no-op si aucune règle).
    # #205 : scoper au user démo (--user) → règles ET transactions du démo uniquement,
    # jamais le mode global (qui appliquerait les règles de tous les users).
    call_command("apply_rules", user=user.email)

    summary = SeedSummary(
        user_email=user.email,
        accounts=len(accounts),
        rules=rules,
        imports=imports,
        created=created,
        skipped=skipped,
    )
    logger.info(
        "seed_demo ok user=%s accounts=%d rules=%d imports=%d created=%d skipped=%d",
        summary.user_email,
        summary.accounts,
        summary.rules,
        summary.imports,
        summary.created,
        summary.skipped,
    )
    return summary


def reset_demo() -> str:
    """Supprime les comptes démo et leurs données (transactions, imports, snapshots,
    cartes). Garde le user démo (re-login OK). Retourne l'email du user démo."""
    user_model = get_user_model()
    email = str(
        settings.DEMO_USER_EMAIL
    )  # settings → Any ; on garantit str pour le retour
    user = user_model.objects.filter(email=email).first()
    if user is None:
        return email
    account_ids = list(
        Account.objects.filter(members=user).values_list("id", flat=True)
    )
    with db_transaction.atomic():
        Transaction.objects.filter(account_id__in=account_ids).delete()
        ImportLog.objects.filter(account_id__in=account_ids).delete()
        BalanceSnapshot.objects.filter(account_id__in=account_ids).delete()
        Card.objects.filter(checking_account__account_id__in=account_ids).delete()
        # Account.delete() cascade CheckingAccount/SavingsAccount (OneToOne).
        Account.objects.filter(id__in=account_ids).delete()
    logger.info("reset_demo ok user=%s accounts=%d", email, len(account_ids))
    return email


# ── Helpers ────────────────────────────────────────────────────────────────────


def _ensure_demo_user():
    """User démo loginable. Re-synchronise le mot de passe avec .env à chaque run."""
    user_model = get_user_model()
    email = settings.DEMO_USER_EMAIL
    password = settings.DEMO_USER_PASSWORD
    if not password:
        raise ValueError(
            "DEMO_USER_PASSWORD est vide — renseigne-le dans .env avant de seeder."
        )
    user = user_model.objects.filter(email=email).first()
    if user is None:
        user = user_model.objects.create_user(email=email, password=password)
        logger.info("demo user created: %s", email)
    else:
        user.set_password(password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
    return user


def _ensure_accounts(user) -> dict[str, Account]:
    """6 comptes démo (idempotent) + carte sur le courant Yuh. Retourne {key: Account}."""
    accounts: dict[str, Account] = {}
    for spec in _DEMO_ACCOUNTS:
        institution = Institution.objects.get(slug=spec.institution)
        account, _ = Account.objects.get_or_create(
            institution=institution,
            name=spec.name,
            defaults={
                "account_type": spec.account_type,
                "currency": spec.currency,
                "iban": spec.iban,
                "contract_number": spec.contract_number,
                "is_active": True,
            },
        )
        account.members.add(user)
        if spec.account_type == Account.AccountType.CHECKING:
            CheckingAccount.objects.get_or_create(account=account)
        else:
            SavingsAccount.objects.get_or_create(
                account=account, defaults={"interest_rate": Decimal("0.75")}
            )
        accounts[spec.key] = account

    # Carte sur le compte COURANT Yuh → résolution carte à l'import des dépenses.
    yuh_checking = accounts["yuh_courant"].checking_account
    Card.objects.get_or_create(
        checking_account=yuh_checking,
        last_four=profiles.DEMO_YUH_CARD_LAST_FOUR,
        defaults={"user": user, "card_type": Card.CardType.DEBIT, "is_active": True},
    )
    return accounts


def _ensure_rules(user) -> int:
    """Règles de catégorisation démo (owner=user), idempotent. Retourne le nombre
    créé ce run. Les catégories visées sont système (owner NULL, référentiel)."""
    created = 0
    for keyword, cat_slug, sub_slug, priority in profiles.DEMO_RULES:
        category = Category.objects.filter(slug=cat_slug, owner__isnull=True).first()
        if category is None:
            logger.warning("règle démo ignorée — catégorie absente : %s", cat_slug)
            continue
        subcategory = (
            SubCategory.objects.filter(slug=sub_slug, owner__isnull=True).first()
            if sub_slug
            else None
        )
        _, was_created = CategorizationRule.objects.get_or_create(
            keyword=keyword,
            owner=user,
            defaults={
                "category": category,
                "subcategory": subcategory,
                "target_field": CategorizationRule.TargetField.DESCRIPTION_RAW,
                "priority": priority,
                "is_active": True,
            },
        )
        if was_created:
            created += 1
    return created


def _resolve_file(
    spec: _DemoFile,
    tmp_dir: Path,
    *,
    months: int,
    anchor: date,
    from_fixtures: bool,
) -> Path:
    """Fichier à importer : fixture committée (--from-fixtures) ou généré à la volée."""
    if from_fixtures:
        path = FIXTURES_DIR / spec.fixture
        if not path.exists():
            raise FileNotFoundError(
                f"Fixture démo absente : {path}. Lance d'abord `manage.py dev_generate_fixtures`."
            )
        return path
    return generators.write_bank_file(spec.bank, tmp_dir, months=months, anchor=anchor)


def _flush_demo_data(accounts: list[Account]) -> None:
    """Vide transactions / imports / snapshots des comptes démo (re-seed propre)."""
    account_ids = [a.id for a in accounts]
    with db_transaction.atomic():
        Transaction.objects.filter(account_id__in=account_ids).delete()
        ImportLog.objects.filter(account_id__in=account_ids).delete()
        BalanceSnapshot.objects.filter(account_id__in=account_ids).delete()


def _ensure_balances(accounts: list[Account]) -> None:
    """Crée un BalanceSnapshot par compte qui n'en a pas encore (sinon le compte est
    invisible dans la vue patrimoine). Solde synthétique plausible par type de compte.

    En pratique seuls les comptes Yuh (CHF, pas de solde dans leur CSV) tombent ici ;
    les comptes CIC (EUR) sont déjà ancrés par l'import. On convertit quand même
    balance_chf via le taux pré-seedé pour ne jamais recréer le trou « — » si un
    compte non-CHF arrive ici un jour (même porte to_chf que l'import)."""
    fallback: dict[str, Decimal] = {
        Account.AccountType.CHECKING: Decimal("3500.00"),
        Account.AccountType.SAVINGS: Decimal("8000.00"),
    }
    today = date.today()
    for account in accounts:
        if BalanceSnapshot.objects.filter(account=account).exists():
            continue
        bal = fallback.get(account.account_type, Decimal("1000.00"))
        BalanceSnapshot.objects.create(
            account=account,
            date=today,
            currency=account.currency,
            balance=bal,
            balance_chf=to_chf(bal, account.currency, today),
            source=BalanceSnapshot.Source.IMPORT,
        )


def _ensure_exchange_rates(anchor: date, months: int) -> None:
    """Pré-seede EUR→CHF en DB pour toute la période → get_exchange_rate (import CIC,
    compte EUR) tape le cache DB, jamais le réseau (seed hors-ligne). Taux synthétique."""
    start = anchor - timedelta(days=(months + 1) * 31)
    rate = Decimal("0.96")
    rows = [
        ExchangeRate(
            date=start + timedelta(days=i),
            from_currency="EUR",
            to_currency="CHF",
            rate=rate,
        )
        for i in range((anchor - start).days + 2)
    ]
    ExchangeRate.objects.bulk_create(rows, ignore_conflicts=True)

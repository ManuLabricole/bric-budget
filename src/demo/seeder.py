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
from datetime import date
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
    Institution,
    SavingsAccount,
)
from demo import generators, profiles
from imports.orchestrator import persist_import_file, prepare_import, run_import
from transactions.models import ImportLog, Transaction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DemoAccount:
    """Spécification d'un compte démo.

    bank      : clé du générateur (generators.write_bank_file).
    fixture   : chemin relatif sous demo/fixtures/ (mode --from-fixtures).
    iban      : normalisé sans espaces = ce que le resolver matche (None pour Yuh,
                résolu par convention).
    """

    bank: str
    fixture: str
    institution: str
    name: str
    account_type: str
    iban: str | None


_DEMO_ACCOUNTS = [
    _DemoAccount(
        bank="ubs_checking",
        fixture="ubs/ubs_checking_demo.csv",
        institution="ubs",
        name="UBS Compte courant",
        account_type=Account.AccountType.CHECKING,
        iban=profiles.DEMO_UBS_CHECKING_IBAN.replace(" ", ""),
    ),
    _DemoAccount(
        bank="ubs_savings",
        fixture="ubs/ubs_savings_demo.csv",
        institution="ubs",
        name="UBS Épargne",
        account_type=Account.AccountType.SAVINGS,
        iban=profiles.DEMO_UBS_SAVINGS_IBAN.replace(" ", ""),
    ),
    _DemoAccount(
        bank="yuh",
        fixture="yuh/yuh_demo.csv",
        institution="yuh",
        name="Yuh",
        account_type=Account.AccountType.CHECKING,
        iban=None,
    ),
]

FIXTURES_DIR = Path(settings.BASE_DIR) / "demo" / "fixtures"


@dataclass
class SeedSummary:
    user_email: str
    accounts: int
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

    if flush:
        _flush_demo_data(list(accounts.values()))

    anchor = date.today()
    imports = created = skipped = 0
    with tempfile.TemporaryDirectory(prefix="bric_demo_") as tmp:
        tmp_dir = Path(tmp)
        for spec in _DEMO_ACCOUNTS:
            path = _resolve_file(
                spec, tmp_dir, months=months, anchor=anchor, from_fixtures=from_fixtures
            )
            prepared = prepare_import(path, user=user)
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

    # Applique les règles de catégorisation existantes (no-op si aucune règle).
    call_command("apply_rules")

    summary = SeedSummary(
        user_email=user.email,
        accounts=len(accounts),
        imports=imports,
        created=created,
        skipped=skipped,
    )
    logger.info(
        "seed_demo ok user=%s accounts=%d imports=%d created=%d skipped=%d",
        summary.user_email,
        summary.accounts,
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
    """Comptes démo (idempotent) + carte Yuh. Retourne {bank_key: Account}."""
    accounts: dict[str, Account] = {}
    for spec in _DEMO_ACCOUNTS:
        institution = Institution.objects.get(slug=spec.institution)
        account, _ = Account.objects.get_or_create(
            institution=institution,
            name=spec.name,
            defaults={
                "account_type": spec.account_type,
                "currency": Account.Currency.CHF,
                "iban": spec.iban,
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
        accounts[spec.bank] = account

    # Carte Yuh (last-four synthétique) → résolution carte à l'import des dépenses.
    yuh_checking = accounts["yuh"].checking_account
    Card.objects.get_or_create(
        checking_account=yuh_checking,
        last_four=profiles.DEMO_YUH_CARD_LAST_FOUR,
        defaults={"user": user, "card_type": Card.CardType.DEBIT, "is_active": True},
    )
    return accounts


def _resolve_file(
    spec: _DemoAccount,
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

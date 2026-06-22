"""
tests/commands/test_backfill_chf.py — backfill des conversions CHF manquantes (#118).

Prouve : amount_chf + balance_chf des comptes non-CHF sont rattrapés via le taux,
--dry-run n'écrit rien, et la commande est idempotente + rejouable (rattrape quand
le taux devient dispo, ne retouche pas ce qui est déjà converti).
"""

import datetime
import hashlib
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from accounts.models import Account, BalanceSnapshot, ExchangeRate, Institution
from transactions.models import Transaction

_DATE = datetime.date(2026, 3, 15)


@pytest.fixture
def eur_account(db):
    bank = Institution.objects.create(
        name="CIC Test", slug="cic-test-backfill", country="FR", default_currency="EUR"
    )
    return Account.objects.create(
        institution=bank, name="CIC EUR", account_type="savings", currency="EUR"
    )


def _seed_rate(rate="0.93"):
    ExchangeRate.objects.create(
        date=_DATE, from_currency="EUR", to_currency="CHF", rate=Decimal(rate)
    )


def _make_tx(account, amount):
    h = hashlib.sha1(f"bf:{amount}".encode(), usedforsecurity=False).hexdigest()
    return Transaction.objects.create(
        account=account,
        date=_DATE,
        amount=Decimal(str(amount)),
        currency=account.currency,
        amount_chf=None,
        description_raw="X",
        import_hash=h,
    )


def _make_snap(account):
    return BalanceSnapshot.objects.create(
        account=account,
        date=_DATE,
        balance=Decimal("1000.00"),
        currency=account.currency,
        balance_chf=None,
        source=BalanceSnapshot.Source.IMPORT,
    )


@pytest.mark.django_db
def test_backfill_converts_missing_chf(eur_account):
    """Taux dispo → balance_chf et amount_chf sont convertis (× taux)."""
    _seed_rate("0.93")  # to_chf tape le cache DB, pas de réseau
    snap = _make_snap(eur_account)
    tx = _make_tx(eur_account, -100.00)

    call_command("backfill_chf")

    snap.refresh_from_db()
    tx.refresh_from_db()
    assert snap.balance_chf == Decimal("930.00")  # 1000 × 0.93
    assert tx.amount_chf == Decimal("-93.00")  # -100 × 0.93


@pytest.mark.django_db
def test_backfill_dry_run_writes_nothing(eur_account):
    """--dry-run compte les candidats mais n'écrit aucune conversion."""
    _seed_rate("0.93")
    snap = _make_snap(eur_account)

    out = StringIO()
    call_command("backfill_chf", "--dry-run", stdout=out)

    snap.refresh_from_db()
    assert snap.balance_chf is None  # rien écrit
    assert "dry-run" in out.getvalue().lower()


@pytest.mark.django_db
def test_backfill_skips_when_no_rate_then_idempotent(eur_account):
    """Sans taux → reste None (best effort). Puis taux dispo → rattrapé. Re-run → stable."""
    snap = _make_snap(eur_account)

    # Pas d'ExchangeRate + API à None → conversion impossible, balance_chf reste None.
    with patch("services.exchange_rates.get_exchange_rate", return_value=None):
        call_command("backfill_chf")
    snap.refresh_from_db()
    assert snap.balance_chf is None

    # Le taux arrive → un nouveau passage rattrape.
    _seed_rate("0.93")
    call_command("backfill_chf")
    snap.refresh_from_db()
    assert snap.balance_chf == Decimal("930.00")

    # Rejouer ne change rien (plus candidat → idempotent).
    call_command("backfill_chf")
    snap.refresh_from_db()
    assert snap.balance_chf == Decimal("930.00")


@pytest.mark.django_db
def test_backfill_leaves_chf_account_untouched(db):
    """Compte CHF : balance_chf NULL n'est PAS un trou de conversion (= balance).
    La commande ne doit pas le toucher (filtre devise ≠ CHF)."""
    bank = Institution.objects.create(
        name="UBS Test", slug="ubs-test-backfill", country="CH", default_currency="CHF"
    )
    chf_account = Account.objects.create(
        institution=bank, name="UBS CHF", account_type="checking", currency="CHF"
    )
    snap = BalanceSnapshot.objects.create(
        account=chf_account,
        date=_DATE,
        balance=Decimal("500.00"),
        currency="CHF",
        balance_chf=None,
        source=BalanceSnapshot.Source.IMPORT,
    )

    call_command("backfill_chf")

    snap.refresh_from_db()
    assert snap.balance_chf is None  # hors périmètre (compte CHF)

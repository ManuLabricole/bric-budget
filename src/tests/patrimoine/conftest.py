"""
tests/patrimoine/conftest.py — Fixtures pour le moteur balance_history.

On crée de vrais objets ORM (Account, BalanceSnapshot, Transaction) — le moteur
lit la DB directement, pas de TransactionDict ici (≠ tests ImportService).

Helpers :
    make_snapshot(account, "YYYY-MM-DD", balance=...) → BalanceSnapshot
    make_tx(account, "YYYY-MM-DD", amount=...)        → Transaction (hash unique)
"""

import datetime
import hashlib
import itertools
from decimal import Decimal

import pytest

from tests.factories import AccountFactory, InstitutionFactory, UserFactory


@pytest.fixture
def user(db):
    return UserFactory(email="patrimoine@test.ch")


@pytest.fixture
def chf_institution(db):
    return InstitutionFactory(
        name="Test CHF", slug="pat-chf", country="CH", default_currency="CHF"
    )


@pytest.fixture
def eur_institution(db):
    return InstitutionFactory(
        name="Test EUR", slug="pat-eur", country="FR", default_currency="EUR"
    )


@pytest.fixture
def chf_account(db, chf_institution, user):
    return AccountFactory(
        institution=chf_institution,
        name="CHF Courant",
        account_type="checking",
        currency="CHF",
        members=[user],
    )


@pytest.fixture
def eur_account(db, eur_institution, user):
    return AccountFactory(
        institution=eur_institution,
        name="EUR Courant",
        account_type="checking",
        currency="EUR",
        members=[user],
    )


# Compteur global pour garantir des import_hash uniques entre tous les appels.
_hash_counter = itertools.count()


def _d(s: str) -> datetime.date:
    """'YYYY-MM-DD' → date."""
    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


@pytest.fixture
def make_snapshot(db):
    from accounts.models import BalanceSnapshot

    def _make(account, date, *, balance=None, computed=None, balance_chf=None):
        return BalanceSnapshot.objects.create(
            account=account,
            date=_d(date),
            balance=None if balance is None else Decimal(str(balance)),
            computed_balance=None if computed is None else Decimal(str(computed)),
            currency=account.currency,
            balance_chf=None if balance_chf is None else Decimal(str(balance_chf)),
        )

    return _make


@pytest.fixture
def make_tx(db):
    from transactions.models import Transaction

    def _make(account, date, amount, *, amount_chf=None):
        n = next(_hash_counter)
        return Transaction.objects.create(
            account=account,
            date=_d(date),
            amount=Decimal(str(amount)),
            currency=account.currency,
            amount_chf=None if amount_chf is None else Decimal(str(amount_chf)),
            description_raw=f"TEST TX {n}",
            import_hash=hashlib.sha1(
                f"pat:{n}".encode(), usedforsecurity=False
            ).hexdigest(),
        )

    return _make

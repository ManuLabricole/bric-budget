"""
tests/budget/conftest.py — Fixtures partagées pour tous les tests budget/.
"""

import pytest
from django.test import Client

from transactions.models import Category, SubCategory


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@budget.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@budget.ch", password="pass"
    )


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.login(email="usera@budget.ch", password="pass")
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.login(email="userb@budget.ch", password="pass")
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Budget Test Bank",
        slug="budget-test-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="COMPTE EXCLUSIF USER A",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank, user_b):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="COMPTE EXCLUSIF USER B",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_b)
    return acc


@pytest.fixture
def category(db):
    return Category.objects.create(
        name="Budget Test Cat",
        slug="budget-test-cat",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


@pytest.fixture
def subcat(db, category):
    return SubCategory.objects.create(
        category=category,
        name="Budget Test Subcat",
        slug="budget-test-subcat",
        is_system=False,
    )

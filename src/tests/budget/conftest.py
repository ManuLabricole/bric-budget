"""
tests/budget/conftest.py — Fixtures partagées pour tous les tests budget/.
"""

import pytest
from django.test import Client

from transactions.models import CategorizationRule, Category, SubCategory


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
    c.force_login(user_a)
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.force_login(user_b)
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Institution

    return Institution.objects.create(
        name="Budget Test Bank",
        slug="budget-test-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=bank,
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
        institution=bank,
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


# --- Catégories perso scopées par owner (#137) ------------------------------


@pytest.fixture
def system_category(db):
    """Catégorie système partagée : owner NULL, visible par tous les users."""
    return Category.objects.create(
        name="Système Partagée",
        slug="systeme-partagee",
        order=1,
        is_system=True,
        owner=None,
    )


@pytest.fixture
def category_a(db, user_a):
    """Catégorie perso de user_a — ne doit JAMAIS être visible par user_b."""
    return Category.objects.create(
        name="PERSO USER A CATEGORY",
        slug="perso-user-a",
        order=50,
        is_system=False,
        owner=user_a,
    )


@pytest.fixture
def category_b(db, user_b):
    """Catégorie perso de user_b — ne doit JAMAIS être visible par user_a."""
    return Category.objects.create(
        name="PERSO USER B CATEGORY",
        slug="perso-user-b",
        order=51,
        is_system=False,
        owner=user_b,
    )


@pytest.fixture
def subcat_b(db, category_b, user_b):
    """Sous-catégorie perso de user_b."""
    return SubCategory.objects.create(
        category=category_b,
        name="PERSO USER B SUBCAT",
        slug="perso-user-b-subcat",
        is_system=False,
        owner=user_b,
    )


# --- Règles de catégorisation scopées par owner (#145) ----------------------


@pytest.fixture
def rule_a(db, category, user_a):
    """Règle de catégorisation appartenant à user_a — invisible/intouchable par user_b."""
    return CategorizationRule.objects.create(
        keyword="RULE-OWNED-BY-A",
        category=category,
        target_field="display_name",
        priority=1,
        is_active=True,
        owner=user_a,
    )


@pytest.fixture
def rule_b(db, category, user_b):
    """Règle de catégorisation appartenant à user_b — invisible/intouchable par user_a."""
    return CategorizationRule.objects.create(
        keyword="RULE-OWNED-BY-B",
        category=category,
        target_field="display_name",
        priority=2,
        is_active=True,
        owner=user_b,
    )

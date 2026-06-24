"""
tests/budget/conftest.py — Fixtures partagées pour tous les tests budget/.

Depuis #194, ces fixtures délèguent aux factories (`tests/factories/`) plutôt que de
recopier des `Model.objects.create(...)`. On conserve les MÊMES noms de fixtures et les
MÊMES valeurs de champs (emails, slugs, noms, ordres, owner) → 0 changement côté tests :
seule la construction passe par les factories, qui centralisent la duplication d'avant.
"""

import pytest
from django.test import Client

from tests.factories import (
    AccountFactory,
    CategorizationRuleFactory,
    CategoryFactory,
    InstitutionFactory,
    SubCategoryFactory,
    SystemCategoryFactory,
    UserFactory,
)


@pytest.fixture
def user_a(db):
    return UserFactory(email="usera@budget.ch")


@pytest.fixture
def user_b(db):
    return UserFactory(email="userb@budget.ch")


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
    return InstitutionFactory(
        name="Budget Test Bank",
        slug="budget-test-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    return AccountFactory(
        institution=bank,
        name="COMPTE EXCLUSIF USER A",
        account_type="checking",
        currency="CHF",
        members=[user_a],
    )


@pytest.fixture
def account_b(db, bank, user_b):
    return AccountFactory(
        institution=bank,
        name="COMPTE EXCLUSIF USER B",
        account_type="checking",
        currency="CHF",
        members=[user_b],
    )


@pytest.fixture
def category(db):
    # owner=None → catégorie système (is_system=False) comme la fixture historique :
    # ni perso A ni perso B, utilisable comme parent neutre dans tous les tests budget.
    return CategoryFactory(
        name="Budget Test Cat",
        slug="budget-test-cat",
        colour_hex="#aaa",
        order=99,
        is_system=False,
        owner=None,
    )


@pytest.fixture
def subcat(db, category):
    return SubCategoryFactory(
        category=category,
        name="Budget Test Subcat",
        slug="budget-test-subcat",
        is_system=False,
    )


# --- Catégories perso scopées par owner (#137) ------------------------------


@pytest.fixture
def system_category(db):
    """Catégorie système partagée : owner NULL, visible par tous les users."""
    return SystemCategoryFactory(
        name="Système Partagée",
        slug="systeme-partagee",
        order=1,
    )


@pytest.fixture
def category_a(db, user_a):
    """Catégorie perso de user_a — ne doit JAMAIS être visible par user_b."""
    return CategoryFactory(
        name="PERSO USER A CATEGORY",
        slug="perso-user-a",
        order=50,
        is_system=False,
        owner=user_a,
    )


@pytest.fixture
def category_b(db, user_b):
    """Catégorie perso de user_b — ne doit JAMAIS être visible par user_a."""
    return CategoryFactory(
        name="PERSO USER B CATEGORY",
        slug="perso-user-b",
        order=51,
        is_system=False,
        owner=user_b,
    )


@pytest.fixture
def subcat_b(db, category_b, user_b):
    """Sous-catégorie perso de user_b."""
    return SubCategoryFactory(
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
    return CategorizationRuleFactory(
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
    return CategorizationRuleFactory(
        keyword="RULE-OWNED-BY-B",
        category=category,
        target_field="display_name",
        priority=2,
        is_active=True,
        owner=user_b,
    )

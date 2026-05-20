"""
tests/test_budget_account_dropdown_idor.py

Tests : protection IDOR sur les dropdowns de comptes dans budget/views.py

Pourquoi ces tests sont critiques :
    budget_index(), budget_panel_transactions(), et budget_category_detail()
    chargeaient Account.objects.filter(is_active=True) sans filtrer par user.
    Un user pouvait donc voir les noms et banques des comptes d'autres users
    dans les dropdowns de filtre — même si leurs transactions restaient cachées.

    Fix appliqué sur les 3 vues :
        Account.objects.for_user(request.user).filter(is_active=True)

Scénarios testés :
    A. budget_index
        1. Le dropdown contient les comptes de l'user connecté
        2. Le dropdown ne contient PAS les comptes d'un autre user

    B. budget_panel_transactions
        3. Le dropdown contient les comptes de l'user connecté
        4. Le dropdown ne contient PAS les comptes d'un autre user

    C. budget_category_detail
        5. Le dropdown contient les comptes de l'user connecté
        6. Le dropdown ne contient PAS les comptes d'un autre user
"""

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import Category

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@dropdown-idor.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@dropdown-idor.ch", password="pass"
    )


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.login(email="usera@dropdown-idor.ch", password="pass")
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.login(email="userb@dropdown-idor.ch", password="pass")
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Dropdown IDOR Bank",
        slug="dropdown-idor-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    """Compte appartenant à user_a — nom distinctif pour l'assertion."""
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
    """Compte appartenant à user_b — ne doit jamais apparaître pour user_a."""
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
        name="Dropdown IDOR Cat",
        slug="dropdown-idor-cat",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


# =============================================================================
# A. budget_index
# =============================================================================


@pytest.mark.django_db
def test_budget_index_shows_own_account_in_dropdown(client_a, account_a, account_b):
    """budget_index affiche le compte de user_a dans le dropdown."""
    response = client_a.get(reverse("budget:index"))
    assert response.status_code == 200
    assert "COMPTE EXCLUSIF USER A" in response.content.decode()


@pytest.mark.django_db
def test_budget_index_hides_other_user_account_from_dropdown(
    client_a, account_a, account_b
):
    """budget_index ne doit PAS afficher le compte de user_b pour user_a."""
    response = client_a.get(reverse("budget:index"))
    assert "COMPTE EXCLUSIF USER B" not in response.content.decode()


# =============================================================================
# B. budget_panel_transactions
# =============================================================================


@pytest.mark.django_db
def test_panel_transactions_shows_own_account_in_dropdown(
    client_a, account_a, account_b
):
    """budget_panel_transactions affiche le compte de user_a."""
    response = client_a.get(reverse("budget:panel_transactions"))
    assert response.status_code == 200
    assert "COMPTE EXCLUSIF USER A" in response.content.decode()


@pytest.mark.django_db
def test_panel_transactions_hides_other_user_account_from_dropdown(
    client_a, account_a, account_b
):
    """budget_panel_transactions ne doit PAS afficher le compte de user_b."""
    response = client_a.get(reverse("budget:panel_transactions"))
    assert "COMPTE EXCLUSIF USER B" not in response.content.decode()


# =============================================================================
# C. budget_category_detail
# =============================================================================


@pytest.mark.django_db
def test_category_detail_shows_own_account_in_dropdown(
    client_a, account_a, account_b, category
):
    """budget_category_detail affiche le compte de user_a dans le sélecteur."""
    response = client_a.get(reverse("budget:category_detail", args=[category.slug]))
    assert response.status_code == 200
    assert "COMPTE EXCLUSIF USER A" in response.content.decode()


@pytest.mark.django_db
def test_category_detail_hides_other_user_account_from_dropdown(
    client_a, account_a, account_b, category
):
    """budget_category_detail ne doit PAS exposer le compte de user_b."""
    response = client_a.get(reverse("budget:category_detail", args=[category.slug]))
    assert "COMPTE EXCLUSIF USER B" not in response.content.decode()

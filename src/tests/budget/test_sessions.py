"""
tests/budget/test_sessions.py

V3 — Tests des vues qui mutent la session Django (sans écrire en DB) :
  - set_period (prev / next / 1m / 3m / 1y)
  - set_period_month
  - set_tab (sorties / entrees / recurrentes)
  - set_cat_tab (transactions / subcategories / objectif)
  - toggle_filter_account
  - toggle_filter_category
"""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Account, Bank
from transactions.models import Category


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="sess@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Cat Session",
        slug="cat-session",
        colour_hex="#abc123",
        order=99,
        is_system=False,
    )


@pytest.fixture
def bank(db):
    return Bank.objects.create(
        name="Sess Bank",
        slug="sess-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    acc = Account.objects.create(
        bank=bank, name="Sess Account", account_type="checking", currency="CHF"
    )
    acc.members.add(user)
    return acc


# =============================================================================
# set_period — prev / next / Xm / Xy
# =============================================================================


@pytest.mark.django_db
def test_set_period_requires_login(client):
    r = client.get(reverse("budget:set_period", args=["prev"]))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["prev", "next", "1m", "3m", "1y"])
def test_set_period_redirects(auth_client, action):
    r = auth_client.get(reverse("budget:set_period", args=[action]))
    assert r.status_code == 302  # redirect vers /budget/ ou referer


@pytest.mark.django_db
def test_set_period_prev_updates_session(auth_client):
    auth_client.get(reverse("budget:set_period", args=["prev"]))
    session = auth_client.session
    assert "budget_period_start" in session
    assert "budget_period_end" in session


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["1m", "3m", "1y"])
def test_set_period_mode_updates_session_mode(auth_client, mode):
    auth_client.get(reverse("budget:set_period", args=[mode]))
    assert auth_client.session.get("budget_period_mode") == mode


@pytest.mark.django_db
def test_set_period_unknown_action_is_noop_redirect(auth_client):
    """Action inconnue → redirect sans crash, session intacte."""
    r = auth_client.get(reverse("budget:set_period", args=["banana"]))
    assert r.status_code == 302
    assert "budget_period_start" not in auth_client.session


# =============================================================================
# set_period_month — saute vers un mois précis
# =============================================================================


@pytest.mark.django_db
def test_set_period_month_requires_login(client):
    r = client.get(reverse("budget:set_period_month", args=[2026, 1]))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_set_period_month_sets_session_to_target_month(auth_client):
    auth_client.get(reverse("budget:set_period_month", args=[2026, 3]))
    session = auth_client.session
    assert session.get("budget_period_mode") == "1m"
    assert session.get("budget_period_start") == "2026-03-01"
    assert session.get("budget_period_end") == "2026-03-31"


# =============================================================================
# set_tab — onglet budget index
# =============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["sorties", "entrees", "recurrentes"])
def test_set_tab_valid_updates_session(auth_client, tab):
    auth_client.get(reverse("budget:set_tab", args=[tab]))
    assert auth_client.session.get("budget_active_tab") == tab


@pytest.mark.django_db
def test_set_tab_invalid_does_not_set_session(auth_client):
    auth_client.get(reverse("budget:set_tab", args=["invalid-tab"]))
    assert "budget_active_tab" not in auth_client.session


# =============================================================================
# set_cat_tab — onglet page catégorie
# =============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["transactions", "subcategories", "objectif"])
def test_set_cat_tab_valid_updates_session(auth_client, tab):
    auth_client.get(reverse("budget:set_cat_tab", args=[tab]))
    assert auth_client.session.get("budget_cat_tab") == tab


@pytest.mark.django_db
def test_set_cat_tab_invalid_does_not_set_session(auth_client):
    auth_client.get(reverse("budget:set_cat_tab", args=["invalid-cat-tab"]))
    assert "budget_cat_tab" not in auth_client.session


# =============================================================================
# toggle_filter_account
# =============================================================================


@pytest.mark.django_db
def test_toggle_filter_account_requires_login(client, account):
    r = client.get(reverse("budget:toggle_filter_account", args=[account.id]))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_toggle_filter_account_adds_id_to_session(auth_client, account):
    auth_client.get(reverse("budget:toggle_filter_account", args=[account.id]))
    assert account.id in auth_client.session.get("budget_filter_accounts", [])


@pytest.mark.django_db
def test_toggle_filter_account_removes_id_when_already_present(auth_client, account):
    """Toggle 2× = retiré de la liste."""
    auth_client.get(reverse("budget:toggle_filter_account", args=[account.id]))
    auth_client.get(reverse("budget:toggle_filter_account", args=[account.id]))
    assert account.id not in auth_client.session.get("budget_filter_accounts", [])


@pytest.mark.django_db
def test_toggle_filter_account_zero_resets_list(auth_client, account):
    """account_id=0 → reset complet."""
    auth_client.get(reverse("budget:toggle_filter_account", args=[account.id]))
    assert auth_client.session.get("budget_filter_accounts")  # non vide
    auth_client.get(reverse("budget:toggle_filter_account", args=[0]))
    assert auth_client.session.get("budget_filter_accounts") == []


# =============================================================================
# toggle_filter_category
# =============================================================================


@pytest.mark.django_db
def test_toggle_filter_category_requires_login(client, cat):
    r = client.get(reverse("budget:toggle_filter_category", args=[cat.slug]))
    assert r.status_code == 302


@pytest.mark.django_db
def test_toggle_filter_category_adds_slug_to_session(auth_client, cat):
    auth_client.get(reverse("budget:toggle_filter_category", args=[cat.slug]))
    assert cat.slug in auth_client.session.get("budget_filter_categories", [])


@pytest.mark.django_db
def test_toggle_filter_category_removes_slug_when_already_present(auth_client, cat):
    auth_client.get(reverse("budget:toggle_filter_category", args=[cat.slug]))
    auth_client.get(reverse("budget:toggle_filter_category", args=[cat.slug]))
    assert cat.slug not in auth_client.session.get("budget_filter_categories", [])


@pytest.mark.django_db
def test_toggle_filter_category_all_resets_list(auth_client, cat):
    auth_client.get(reverse("budget:toggle_filter_category", args=[cat.slug]))
    assert auth_client.session.get("budget_filter_categories")
    auth_client.get(reverse("budget:toggle_filter_category", args=["all"]))
    assert auth_client.session.get("budget_filter_categories") == []

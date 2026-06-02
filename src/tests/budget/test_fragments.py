"""
tests/budget/test_fragments.py

V2 — Tests des fragments HTMX (GET) :
  - budget_modal_rule_intro       : modal step 1 wizard règle
  - budget_modal_target_create    : modal BudgetTarget
  - budget_panel_category_picker  : fragment picker dans le right panel
  - budget_panel_navigate         : nav période côté panel transactions (action prev/next/Xm)
  - budget_rule_live_preview      : preview live keyword
  - budget_rule_standalone_preview: preview multi-keyword

Tous renvoient des partials (pas de <html>, pas de <!DOCTYPE>).
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Account, Bank
from transactions.models import Category, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="frag@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Cat Fragments",
        slug="cat-fragments",
        colour_hex="#4ade80",
        order=99,
        is_system=False,
    )


@pytest.fixture
def bank(db):
    return Bank.objects.create(
        name="Frag Bank",
        slug="frag-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    acc = Account.objects.create(
        bank=bank, name="Frag Account", account_type="checking", currency="CHF"
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def tx(db, account, cat):
    return Transaction.objects.create(
        account=account,
        category=cat,
        date="2026-01-15",
        amount=-50,
        currency="CHF",
        amount_chf=-50,
        description_raw="MIGROS LAUSANNE",
        display_name="MIGROS LAUSANNE",
        import_hash=hashlib.sha256(b"frag-tx").hexdigest(),
    )


def _is_partial(content):
    """Un partial HTMX ne doit pas contenir <!DOCTYPE> ni <html."""
    return "<!DOCTYPE html>" not in content and "<html" not in content


# =============================================================================
# modal_rule_intro — GET
# =============================================================================


@pytest.mark.django_db
def test_modal_rule_intro_requires_login(client, tx):
    r = client.get(
        reverse("budget:modal_rule_intro") + f"?tx_id={tx.pk}&keyword=MIGROS"
    )
    assert r.status_code == 302


@pytest.mark.django_db
def test_modal_rule_intro_returns_partial(auth_client, tx):
    r = auth_client.get(
        reverse("budget:modal_rule_intro") + f"?tx_id={tx.pk}&keyword=MIGROS"
    )
    assert r.status_code == 200
    assert _is_partial(r.content.decode())


@pytest.mark.django_db
def test_modal_rule_intro_404_for_unknown_tx(auth_client):
    r = auth_client.get(reverse("budget:modal_rule_intro") + "?tx_id=999999&keyword=X")
    assert r.status_code == 404


# =============================================================================
# modal_target_create — GET
# =============================================================================


@pytest.mark.django_db
def test_modal_target_create_requires_login(client):
    r = client.get(reverse("budget:modal_target_create"))
    assert r.status_code == 302


@pytest.mark.django_db
def test_modal_target_create_without_cat_id_returns_list(auth_client, cat):
    """Sans category_id → liste de toutes les catégories avec leurs objectifs."""
    r = auth_client.get(reverse("budget:modal_target_create"))
    assert r.status_code == 200
    assert _is_partial(r.content.decode())
    # Le nom de la catégorie doit apparaître dans la liste
    assert cat.name in r.content.decode()


@pytest.mark.django_db
def test_modal_target_create_with_cat_id_returns_form(auth_client, cat):
    r = auth_client.get(
        reverse("budget:modal_target_create") + f"?category_id={cat.id}"
    )
    assert r.status_code == 200
    assert _is_partial(r.content.decode())


# =============================================================================
# panel_category_picker — GET
# =============================================================================


@pytest.mark.django_db
def test_panel_category_picker_requires_login(client, tx):
    r = client.get(reverse("budget:panel_category_picker") + f"?tx_id={tx.pk}")
    assert r.status_code == 302


@pytest.mark.django_db
def test_panel_category_picker_returns_partial(auth_client, tx):
    r = auth_client.get(reverse("budget:panel_category_picker") + f"?tx_id={tx.pk}")
    assert r.status_code == 200
    assert _is_partial(r.content.decode())


# =============================================================================
# panel_navigate — GET (modifie session puis renvoie le panel transactions)
# =============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["prev", "next", "1m", "3m", "1y"])
def test_panel_navigate_action_returns_200(auth_client, action):
    r = auth_client.get(reverse("budget:panel_navigate", args=[action]))
    assert r.status_code == 200
    assert _is_partial(r.content.decode())


@pytest.mark.django_db
def test_panel_navigate_prev_updates_session(auth_client):
    """Avant : pas de période → fallback today. Après prev : période start - 1 mois."""
    auth_client.get(reverse("budget:panel_navigate", args=["prev"]))
    session = auth_client.session
    assert "budget_period_start" in session
    assert "budget_period_end" in session


# =============================================================================
# rule_live_preview — GET
# =============================================================================


@pytest.mark.django_db
def test_rule_live_preview_requires_login(client, cat):
    r = client.get(
        reverse("budget:rule_live_preview") + f"?keyword=MIGROS&category_id={cat.id}"
    )
    assert r.status_code == 302


@pytest.mark.django_db
def test_rule_live_preview_returns_partial(auth_client, cat, tx):
    r = auth_client.get(
        reverse("budget:rule_live_preview") + f"?keyword=MIGROS&category_id={cat.id}"
    )
    assert r.status_code == 200
    assert _is_partial(r.content.decode())


# =============================================================================
# rule_standalone_preview — GET
# =============================================================================


@pytest.mark.django_db
def test_rule_standalone_preview_requires_login(client, cat):
    r = client.get(
        reverse("budget:rule_standalone_preview") + f"?kw=MIGROS&category_id={cat.id}"
    )
    assert r.status_code == 302


@pytest.mark.django_db
def test_rule_standalone_preview_returns_partial(auth_client, cat, tx):
    r = auth_client.get(
        reverse("budget:rule_standalone_preview") + f"?kw=MIGROS&category_id={cat.id}"
    )
    assert r.status_code == 200
    assert _is_partial(r.content.decode())


@pytest.mark.django_db
def test_rule_standalone_preview_no_keywords_returns_empty_state(auth_client, cat):
    """Sans aucun kw → preview vide, mais 200 (le template gère le cas)."""
    r = auth_client.get(
        reverse("budget:rule_standalone_preview") + f"?category_id={cat.id}"
    )
    assert r.status_code == 200

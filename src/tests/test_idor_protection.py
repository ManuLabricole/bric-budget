"""
tests/test_idor_protection.py

Tests : protection IDOR sur les vues Transaction de budget/views.py

Pourquoi ces tests sont critiques :
    Un utilisateur connecté (user B) ne doit jamais pouvoir lire ou modifier
    les transactions d'un autre utilisateur (user A), même en connaissant le PK.
    La protection repose sur Transaction.objects.for_user(request.user) qui
    filtre via account__members (M2M introduit en T4c).

    Sans ce filtre : get_object_or_404(Transaction, pk=tx_id) retourne 200
    pour n'importe quel PK valide, quelle que soit l'appartenance du compte.
    Avec le filtre : 404 si le compte n'est pas dans account.members de l'user.

Scénarios testés (7 vues protégées) :
    1.  toggle_ignore       — user B → tx de user A → 404
    2.  panel_tx_detail     — user B → tx de user A → 404
    3.  categorize          — user B → tx de user A → 404
    4.  panel_rule_create   — user B → tx de user A → 404
    5.  rule_preview        — user B → tx de user A → 404
    6.  toggle_reconcile    — user B → tx de user A → 404

    Et pour chaque vue : user A → sa propre tx → 200 (accès légitime)
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import Category, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="usera@idor.ch", password="pass")


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="userb@idor.ch", password="pass")


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.login(email="usera@idor.ch", password="pass")
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.login(email="userb@idor.ch", password="pass")
    return c


@pytest.fixture
def account_a(db, user_a):
    """Compte appartenant à user A uniquement."""
    from accounts.models import Account, Bank

    bank = Bank.objects.create(
        name="IDOR Bank A",
        slug="idor-bank-a",
        country="CH",
        default_currency="CHF",
    )
    acc = Account.objects.create(
        bank=bank,
        name="Account A",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Alimentation",
        slug="alimentation-idor",
        colour_hex="#aaa",
        order=50,
        is_system=False,
    )


def make_tx(account, seed):
    return Transaction.objects.create(
        account=account,
        date="2026-01-15",
        amount=-20,
        currency="CHF",
        amount_chf=-20,
        description_raw=f"TX IDOR {seed}",
        display_name=f"TX IDOR {seed}",
        import_hash=hashlib.sha256(f"idor:{seed}".encode()).hexdigest(),
    )


# =============================================================================
# Tests IDOR — user B ne peut pas accéder aux tx de user A
# =============================================================================


@pytest.mark.django_db
def test_idor_toggle_ignore_blocked_for_other_user(client_b, account_a):
    """
    user B POST sur toggle_ignore d'une tx appartenant à user A → 404.
    Sans for_user(), cette vue retournait 200 et modifiait la tx.
    """
    tx = make_tx(account_a, "toggle-ignore-b")

    resp = client_b.post(
        reverse("budget:toggle_ignore", args=[tx.id]), {"source": "list"}
    )

    assert resp.status_code == 404
    tx.refresh_from_db()
    assert tx.is_ignored is False  # la tx n'a pas été modifiée


@pytest.mark.django_db
def test_idor_toggle_ignore_allowed_for_owner(client_a, account_a):
    """user A peut toggler sa propre tx → 200."""
    tx = make_tx(account_a, "toggle-ignore-a")

    resp = client_a.post(
        reverse("budget:toggle_ignore", args=[tx.id]), {"source": "list"}
    )

    assert resp.status_code == 200
    tx.refresh_from_db()
    assert tx.is_ignored is True  # toggled


@pytest.mark.django_db
def test_idor_panel_tx_detail_blocked_for_other_user(client_b, account_a):
    """
    user B GET sur panel_tx_detail d'une tx de user A → 404.
    """
    tx = make_tx(account_a, "detail-b")

    resp = client_b.get(reverse("budget:panel_tx_detail"), {"tx_id": tx.id})

    assert resp.status_code == 404


@pytest.mark.django_db
def test_idor_panel_tx_detail_allowed_for_owner(client_a, account_a):
    """user A GET panel_tx_detail de sa propre tx → 200."""
    tx = make_tx(account_a, "detail-a")

    resp = client_a.get(reverse("budget:panel_tx_detail"), {"tx_id": tx.id})

    assert resp.status_code == 200


@pytest.mark.django_db
def test_idor_categorize_blocked_for_other_user(client_b, account_a, cat):
    """
    user B POST categorize sur une tx de user A → 404.
    La catégorie de la tx ne doit pas changer.
    """
    tx = make_tx(account_a, "categorize-b")

    resp = client_b.post(
        reverse("budget:categorize"),
        {"tx_id": tx.id, "category_id": cat.id},
    )

    assert resp.status_code == 404
    tx.refresh_from_db()
    assert tx.category is None  # non modifiée


@pytest.mark.django_db
def test_idor_categorize_allowed_for_owner(client_a, account_a, cat):
    """user A peut catégoriser sa propre tx → 200."""
    tx = make_tx(account_a, "categorize-a")

    resp = client_a.post(
        reverse("budget:categorize"),
        {"tx_id": tx.id, "category_id": cat.id},
    )

    assert resp.status_code == 200
    tx.refresh_from_db()
    assert tx.category == cat


@pytest.mark.django_db
def test_idor_panel_rule_create_blocked_for_other_user(client_b, account_a, cat):
    """
    user B GET panel_rule_create sur une tx de user A → 404.
    cat_id passé pour éviter que le crash vienne d'une catégorie manquante.
    """
    tx = make_tx(account_a, "rule-create-b")

    resp = client_b.get(
        reverse("budget:panel_rule_create"),
        {"tx_id": tx.id, "cat_id": cat.id},
    )

    assert resp.status_code == 404


@pytest.mark.django_db
def test_idor_panel_rule_create_allowed_for_owner(client_a, account_a, cat):
    """user A peut ouvrir panel_rule_create sur sa tx → 200."""
    tx = make_tx(account_a, "rule-create-a")

    resp = client_a.get(
        reverse("budget:panel_rule_create"),
        {"tx_id": tx.id, "cat_id": cat.id},
    )

    assert resp.status_code == 200


@pytest.mark.django_db
def test_idor_rule_preview_blocked_for_other_user(client_b, account_a, cat):
    """
    user B POST rule_preview sur une tx de user A → 404.
    rule_preview est POST-only.
    """
    tx = make_tx(account_a, "rule-preview-b")

    resp = client_b.post(
        reverse("budget:rule_preview"),
        {"tx_id": tx.id, "keyword": "TEST", "cat_id": cat.id},
    )

    assert resp.status_code == 404


@pytest.mark.django_db
def test_idor_toggle_reconcile_blocked_for_other_user(client_b, account_a):
    """
    user B POST toggle_reconcile sur une tx de user A → 404.
    is_reconciled ne doit pas changer.
    """
    tx = make_tx(account_a, "reconcile-b")

    resp = client_b.post(
        reverse("budget:toggle_reconcile", args=[tx.id]),
        {"source": "list"},
    )

    assert resp.status_code == 404
    tx.refresh_from_db()
    assert tx.is_reconciled is False  # non modifiée


@pytest.mark.django_db
def test_idor_toggle_reconcile_allowed_for_owner(client_a, account_a):
    """user A peut toggler is_reconciled de sa propre tx → 200."""
    tx = make_tx(account_a, "reconcile-a")

    resp = client_a.post(
        reverse("budget:toggle_reconcile", args=[tx.id]),
        {"source": "list"},
    )

    assert resp.status_code == 200
    tx.refresh_from_db()
    assert tx.is_reconciled is True

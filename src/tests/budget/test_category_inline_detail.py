"""
tests/budget/test_category_inline_detail.py — Carte détail INLINE sur category_detail.

La page budget « détail catégorie » affiche le détail d'une transaction dans une carte
fixe #cat-tx-detail (sous le donut), via le composant partagé _panel_tx_detail_inline.html
(le même que patrimoine #ac-tx-detail). On vérifie le câblage des deux sources :
  - source="category"        (ligne/œil) → la ligne seule, contexte préservé.
  - source="category_detail" (toggles de la carte) → carte + ligne OOB.
Plus : cashflow refresh sur ignore (pas sur pointer) et HX-Redirect sur recatégorisation.
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Account, Institution
from transactions.models import Category, Transaction


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="cat-inline@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Courses", slug="courses-inline", colour_hex="#5fae9f", order=10
    )


@pytest.fixture
def account(db, user):
    bank = Institution.objects.create(
        name="Inline Bank", slug="inline-bank", country="CH", default_currency="CHF"
    )
    acc = Account.objects.create(
        institution=bank, name="Inline Account", account_type="checking", currency="CHF"
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def tx(db, account, cat):
    # Date dans le mois courant (période par défaut de category_detail).
    return Transaction.objects.create(
        account=account,
        category=cat,
        date="2026-06-05",
        amount=-50,
        currency="CHF",
        amount_chf=-50,
        description_raw="MIGROS LAUSANNE",
        display_name="MIGROS LAUSANNE",
        import_hash=hashlib.sha256(b"cat-inline-tx").hexdigest(),
    )


# ── GET détail → carte inline ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_panel_tx_detail_category_renders_inline_card(auth_client, tx):
    """source=category → carte inline ciblant #cat-tx-detail (pas l'overlay budget)."""
    resp = auth_client.get(
        reverse("budget:panel_tx_detail") + f"?tx_id={tx.id}&source=category"
    )
    html = resp.content.decode()

    assert resp.status_code == 200
    assert "Détails de la transaction" in html
    assert "Inclure dans l'analyse budgétaire" in html
    assert 'hx-target="#cat-tx-detail"' in html  # toggles + chevron ciblent la carte


# ── Toggles de la carte (source=category_detail) ──────────────────────────────


@pytest.mark.django_db
def test_toggle_ignore_category_detail_flips_card_oob_and_cashflow(auth_client, tx):
    """Carte : bascule is_ignored + carte + ligne OOB + signal cashflow (totaux changés)."""
    assert tx.is_ignored is False

    resp = auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "category_detail"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.is_ignored is True
    assert "Détails de la transaction" in html  # carte re-rendue
    assert "hx-swap-oob" in html  # ligne centrale OOB
    assert "data-cashflow-refresh" in html  # → refresh Sankey/KPIs


@pytest.mark.django_db
def test_toggle_reconcile_category_detail_no_cashflow_signal(auth_client, tx):
    """Pointer ne change pas les totaux → pas de signal cashflow (carte + OOB seulement)."""
    resp = auth_client.post(
        reverse("budget:toggle_reconcile", args=[tx.id]),
        {"source": "category_detail"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.is_reconciled is True
    assert "Détails de la transaction" in html
    assert "hx-swap-oob" in html
    assert "data-cashflow-refresh" not in html


# ── Bouton ligne (source=category) ────────────────────────────────────────────


@pytest.mark.django_db
def test_toggle_from_list_row_category_returns_row_with_context(auth_client, tx):
    """Œil de la ligne (source=category) → la LIGNE seule, contexte #cat-tx-detail préservé."""
    resp = auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "category"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.is_ignored is True
    assert "Détails de la transaction" not in html  # pas la carte
    assert 'hx-target="#cat-tx-detail"' in html  # la ligne garde son contexte


# ── Chevron → picker INLINE dans la carte ─────────────────────────────────────


@pytest.mark.django_db
def test_category_picker_renders_inline_in_card(auth_client, tx):
    """source=category → le picker se rend dans #cat-tx-detail (pas l'overlay)."""
    resp = auth_client.get(
        reverse("budget:panel_category_picker") + f"?tx_id={tx.id}&source=category"
    )
    html = resp.content.decode()

    assert resp.status_code == 200
    assert "cat-tx-detail" in html  # × / retour reviennent à la carte inline


# ── Recatégorisation depuis le picker inline ──────────────────────────────────


@pytest.mark.django_db
def test_categorize_category_redirects_to_refresh_page(auth_client, tx, cat):
    """source=category → HX-Redirect : la tx peut quitter la catégorie, on recharge la page."""
    resp = auth_client.post(
        reverse("budget:categorize"),
        {"tx_id": tx.id, "category_id": cat.id, "source": "category"},
    )

    assert resp.has_header("HX-Redirect")


# ── Page complète ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_category_detail_page_renders_inline_card_and_rows_target_it(
    auth_client, tx, cat
):
    """La page category_detail rend le conteneur #cat-tx-detail et les lignes le ciblent."""
    resp = auth_client.get(reverse("budget:category_detail", args=[cat.slug]))
    html = resp.content.decode()

    assert resp.status_code == 200
    assert 'id="cat-tx-detail"' in html
    assert "source=category" in html  # la ligne charge le détail inline

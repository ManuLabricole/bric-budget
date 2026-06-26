"""
tests/patrimoine/test_asset_class_view.py — Vue page classe d'actifs.

Couvre les 3 comportements ajoutés à la page asset_class :
  1. Pastilles couleur dans l'onglet Comptes — couleur = _STACK_PALETTE[index],
     identique à la courbe et au treemap.
  2. Carte détail inline (#ac-tx-detail) — clic transaction → détail rendu via
     source="patrimoine" (pas l'overlay).
  3. Toggles inline connectés — toggle_ignore / toggle_reconcile avec source="patrimoine"
     basculent le flag ET renvoient une mise à jour OOB de la ligne centrale.

Sécurité : les endpoints sont les vues budget (déjà scopées for_user — cf. test_idor).
"""

import pytest
from django.urls import reverse

from patrimoine.services.chart_data import _STACK_PALETTE


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def second_chf_account(db, chf_institution, user):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=chf_institution,
        name="CHF Livret",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user)
    return acc


# ── #1 Pastilles couleur onglet Comptes ──────────────────────────────────────


@pytest.mark.django_db
def test_comptes_tab_renders_palette_dot_per_account(
    client_logged, chf_account, make_snapshot
):
    """Chaque compte affiche une pastille colorée = couleur de sa série dans le graphe."""
    make_snapshot(chf_account, "2026-06-01", balance=1000, balance_chf=1000)

    resp = client_logged.get(
        reverse("patrimoine:asset_class", args=["comptes-courants"])
    )

    assert resp.status_code == 200
    # Pastille = style inline `background-color:` (≠ JSON `"color":` du graphe/treemap).
    # Le 1er compte → 1ʳᵉ couleur de la palette (même index que la courbe).
    assert f"background-color: {_STACK_PALETTE[0]}" in resp.content.decode()


@pytest.mark.django_db
def test_account_color_matches_position_index(
    client_logged, chf_account, second_chf_account, make_snapshot
):
    """2 comptes → couleurs palette[0] et palette[1] (ordre institution__name, name)."""
    make_snapshot(chf_account, "2026-06-01", balance=1000, balance_chf=1000)
    make_snapshot(second_chf_account, "2026-06-01", balance=500, balance_chf=500)

    resp = client_logged.get(
        reverse("patrimoine:asset_class", args=["comptes-courants"])
    )
    html = resp.content.decode()

    # Ordre alpha : "CHF Courant" puis "CHF Livret" → palette[0], palette[1].
    assert f"background-color: {_STACK_PALETTE[0]}" in html
    assert f"background-color: {_STACK_PALETTE[1]}" in html


# ── #4 Carte détail inline ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_transactions_tab_renders_inline_detail_card_and_targets_it(
    client_logged, chf_account, make_tx, user
):
    """Onglet Transactions : carte vide #ac-tx-detail + la ligne tx la cible (pas l'overlay)."""
    make_tx(chf_account, "2026-06-08", amount=-30)

    # Bascule l'onglet en session via l'endpoint dédié, puis charge la page.
    client_logged.get(
        reverse(
            "patrimoine:set_asset_class_tab", args=["comptes-courants", "transactions"]
        )
    )
    resp = client_logged.get(
        reverse("patrimoine:asset_class", args=["comptes-courants"])
    )
    html = resp.content.decode()

    assert resp.status_code == 200
    assert 'id="ac-tx-detail"' in html  # la 4ᵉ carte existe
    assert (
        'hx-target="#ac-tx-detail"' in html
    )  # la ligne cible la carte, pas #panel-content
    assert "source=patrimoine" in html  # le détail est chargé en mode inline


@pytest.mark.django_db
def test_panel_tx_detail_patrimoine_renders_inline_card(
    client_logged, chf_account, make_tx
):
    """source=patrimoine → carte détail inline (titre + toggles), pas l'overlay budget."""
    tx = make_tx(chf_account, "2026-06-08", amount=-42)

    resp = client_logged.get(
        reverse("budget:panel_tx_detail") + f"?tx_id={tx.id}&source=patrimoine"
    )
    html = resp.content.decode()

    assert resp.status_code == 200
    assert "Détails de la transaction" in html
    assert "Inclure dans l'analyse budgétaire" in html
    assert "Pointer la transaction" in html


@pytest.mark.django_db
def test_categorize_patrimoine_updates_card_and_central_row(
    client_logged, chf_account, make_tx
):
    """Recatégoriser depuis la carte → catégorie assignée + carte + ligne centrale OOB.

    Régression : avant, le picker patrimoine renvoyait la liste budget globale → la
    catégorie n'était PAS mise à jour dans la liste centrale patrimoine.
    """
    from transactions.models import Category

    cat = Category.objects.create(
        name="Loisirs", slug="loisirs-pat", colour_hex="#9b7ae8", order=20
    )
    tx = make_tx(chf_account, "2026-06-08", amount=-25)
    assert tx.category_id is None

    resp = client_logged.post(
        reverse("budget:categorize"),
        {"tx_id": tx.id, "category_id": cat.id, "source": "patrimoine"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.category_id == cat.id
    # La carte est re-rendue avec la nouvelle catégorie…
    assert "Détails de la transaction" in html
    assert "Loisirs" in html
    # …et la ligne centrale est mise à jour hors-bande (OOB) → liste à jour sans reload.
    assert "hx-swap-oob" in html
    assert f"tx-{tx.id}" in html
    # Surtout PAS un HX-Redirect (ça, c'est le comportement category).
    assert not resp.has_header("HX-Redirect")


@pytest.mark.django_db
def test_inline_card_shows_rule_badge_when_categorized_by_rule(
    client_logged, chf_account, make_tx
):
    """categorization_source=rule → badge doré 'Règle intelligente appliquée'."""
    from transactions.models import Category

    cat = Category.objects.create(
        name="Assurance", slug="assurance-test", colour_hex="#5d6bf0", order=50
    )
    tx = make_tx(chf_account, "2026-06-08", amount=-99)
    tx.category = cat
    tx.categorization_source = "rule"
    tx.save(update_fields=["category", "categorization_source"])

    resp = client_logged.get(
        reverse("budget:panel_tx_detail") + f"?tx_id={tx.id}&source=patrimoine"
    )

    assert "Règle intelligente appliquée".upper() in resp.content.decode().upper()


# ── #3 Toggles inline connectés ───────────────────────────────────────────────


@pytest.mark.django_db
def test_toggle_ignore_patrimoine_detail_flips_and_returns_inline_card_plus_oob(
    client_logged, chf_account, make_tx
):
    """Carte (source=patrimoine_detail) : bascule is_ignored + carte inline + ligne OOB."""
    tx = make_tx(chf_account, "2026-06-08", amount=-12)
    assert tx.is_ignored is False

    resp = client_logged.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "patrimoine_detail"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.is_ignored is True
    # La carte inline est re-rendue…
    assert "Détails de la transaction" in html
    # …et la ligne centrale est mise à jour hors-bande (OOB) pour refléter l'état.
    assert "hx-swap-oob" in html
    assert f"tx-{tx.id}" in html


@pytest.mark.django_db
def test_toggle_reconcile_patrimoine_detail_flips_and_returns_inline_card(
    client_logged, chf_account, make_tx
):
    """Carte (source=patrimoine_detail) : bascule is_reconciled + carte inline + OOB."""
    tx = make_tx(chf_account, "2026-06-08", amount=-7)
    assert tx.is_reconciled is False

    resp = client_logged.post(
        reverse("budget:toggle_reconcile", args=[tx.id]),
        {"source": "patrimoine_detail"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.is_reconciled is True
    assert "Détails de la transaction" in html
    assert "hx-swap-oob" in html


@pytest.mark.django_db
def test_toggle_from_list_row_patrimoine_returns_row_with_preserved_context(
    client_logged, chf_account, make_tx
):
    """Bouton ligne (source=patrimoine) : bascule + renvoie la LIGNE en gardant son contexte.

    Pas la carte détail (sinon elle s'injecterait dans #tx-id, cible du bouton œil).
    """
    tx = make_tx(chf_account, "2026-06-08", amount=-12)

    resp = client_logged.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "patrimoine"},
    )
    html = resp.content.decode()

    tx.refresh_from_db()
    assert tx.is_ignored is True
    # On renvoie la ligne (pas la carte) en préservant panel_target → clics suivants
    # rouvrent bien la carte inline et non l'overlay.
    assert "Détails de la transaction" not in html
    assert 'hx-target="#ac-tx-detail"' in html
    assert "source=patrimoine" in html

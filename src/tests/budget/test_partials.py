"""
tests/budget/test_partials.py — Couche de tests des partials HTMX du budget (#157).

But : pour chaque vue qui BRANCHE sur l'en-tête `HX-Request`, prouver les DEUX chemins :
  - requête HTMX  → un PARTIAL (`_xxx.html`), inner HTML (jamais `<!DOCTYPE html>`) ;
  - requête nue   → page complète OU redirect (PRG fallback).

Vues couvertes (cf. `grep "HX-Request" src/budget/`) :
  - budget_toggle_filter_account  (core.py) — 3 sorties : index left-section / panel tx / redirect
  - budget_toggle_filter_category (core.py) — idem

Détection côté vue = `request.headers.get("HX-Request")` (HEADER BRUT, pas `request.htmx`)
→ on simule HTMX via `HTTP_HX_REQUEST="true"`, et le contexte d'appel via
`HTTP_HX_TARGET="budget-left-section"` (cf. rules/htmx.md, `hx-target`).

Données : fixtures du conftest budget (déléguées aux factories #194, SR-008) — pas de
`create()` inline ni d'IBAN réel.
"""

import pytest
from django.urls import reverse

# Header brut HTMX (cf. rules/htmx.md : request.headers.get("HX-Request")).
_HX = {"HTTP_HX_REQUEST": "true"}
# Contexte d'appel = swap de la section gauche de l'index (dropdown reste ouvert).
_HX_LEFT = {"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "budget-left-section"}


# =============================================================================
# budget_toggle_filter_account
# =============================================================================


@pytest.mark.django_db
def test_toggle_filter_account_htmx_panel_returns_tx_list_partial(client_a, account_a):
    """HX sans HX-Target ciblé → fragment panel transactions (_panel_tx_list), inner HTML."""
    resp = client_a.get(
        reverse("budget:toggle_filter_account", args=[account_a.id]), **_HX
    )
    assert resp.status_code == 200
    assert "budget/_panel_tx_list.html" in {t.name for t in resp.templates}
    assert b"<!DOCTYPE html>" not in resp.content


@pytest.mark.django_db
def test_toggle_filter_account_htmx_left_target_returns_left_section_partial(
    client_a, account_a
):
    """HX + HX-Target=budget-left-section → fragment _budget_left_section, inner HTML."""
    resp = client_a.get(
        reverse("budget:toggle_filter_account", args=[account_a.id]), **_HX_LEFT
    )
    assert resp.status_code == 200
    names = {t.name for t in resp.templates}
    assert "budget/partials/_budget_left_section.html" in names
    assert "budget/index.html" not in names  # surtout pas la page complète
    assert b"<!DOCTYPE html>" not in resp.content
    assert b'id="budget-left-section"' in resp.content


@pytest.mark.django_db
def test_toggle_filter_account_non_htmx_redirects(client_a, account_a):
    """Requête nue (navigation directe) → redirect PRG, jamais un partial nu."""
    resp = client_a.get(reverse("budget:toggle_filter_account", args=[account_a.id]))
    assert resp.status_code == 302


# =============================================================================
# budget_toggle_filter_category
# =============================================================================


@pytest.mark.django_db
def test_toggle_filter_category_htmx_panel_returns_tx_list_partial(client_a, category):
    """HX sans HX-Target ciblé → fragment panel transactions (_panel_tx_list), inner HTML."""
    resp = client_a.get(
        reverse("budget:toggle_filter_category", args=[category.slug]), **_HX
    )
    assert resp.status_code == 200
    assert "budget/_panel_tx_list.html" in {t.name for t in resp.templates}
    assert b"<!DOCTYPE html>" not in resp.content


@pytest.mark.django_db
def test_toggle_filter_category_htmx_left_target_returns_left_section_partial(
    client_a, category
):
    """HX + HX-Target=budget-left-section → fragment _budget_left_section, inner HTML."""
    resp = client_a.get(
        reverse("budget:toggle_filter_category", args=[category.slug]), **_HX_LEFT
    )
    assert resp.status_code == 200
    names = {t.name for t in resp.templates}
    assert "budget/partials/_budget_left_section.html" in names
    assert "budget/index.html" not in names
    assert b"<!DOCTYPE html>" not in resp.content
    assert b'id="budget-left-section"' in resp.content


@pytest.mark.django_db
def test_toggle_filter_category_non_htmx_redirects_to_index(client_a, category):
    """Requête nue → redirect vers budget:index (PRG fallback)."""
    resp = client_a.get(reverse("budget:toggle_filter_category", args=[category.slug]))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("budget:index")

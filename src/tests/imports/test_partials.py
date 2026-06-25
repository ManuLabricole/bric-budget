"""
tests/imports/test_partials.py — Couche de tests des partials HTMX de l'import (#157).

But : pour chaque vue qui BRANCHE sur l'en-tête `HX-Request`, prouver les DEUX chemins :
  - requête HTMX  → un PARTIAL (`_activity_section.html`), inner HTML (jamais `<!DOCTYPE html>`) ;
  - requête nue   → redirect vers `imports:upload` (PRG fallback).

Vues couvertes (cf. `grep "HX-Request" src/imports/views.py`) :
  - set_period            (set-period/<action>/) — change période/offset graphe activité
  - toggle_filter_account (toggle-filter/account/<ref>/) — masque un compte du graphe

Détection côté vue = `request.headers.get("HX-Request")` (HEADER BRUT, pas `request.htmx`)
→ on simule HTMX via `HTTP_HX_REQUEST="true"`.

Données via factories (#194, SR-008 : IBAN/contrat générés, jamais réels).
"""

import pytest
from django.urls import reverse

from tests.factories import AccountFactory, UserFactory

# Header brut HTMX (cf. rules/htmx.md : request.headers.get("HX-Request")).
_HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def user(db):
    return UserFactory(email="imports-partials@test.ch")


@pytest.fixture
def account(db, user):
    # Compte actif membre de `user` → apparaît dans le graphe d'activité scopé IDOR.
    return AccountFactory(name="Import Partials Account", members=[user])


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


# =============================================================================
# set_period — change la période du graphe d'activité
# =============================================================================


@pytest.mark.django_db
def test_set_period_htmx_returns_activity_section_partial(client_logged, account):
    """HX → fragment _activity_section, inner HTML (jamais la page d'upload complète)."""
    resp = client_logged.get(reverse("imports:set_period", args=["3m"]), **_HX)
    assert resp.status_code == 200
    assert "imports/partials/_activity_section.html" in {t.name for t in resp.templates}
    assert b"<!DOCTYPE html>" not in resp.content
    assert b'id="activity-chart-section"' in resp.content
    # L'action a bien muté la session (PRG : l'état UI vit en session).
    assert client_logged.session["import_period_mode"] == "3m"


@pytest.mark.django_db
def test_set_period_non_htmx_redirects_to_upload(client_logged, account):
    """Requête nue (navigation directe) → redirect vers imports:upload, pas un partial nu."""
    resp = client_logged.get(reverse("imports:set_period", args=["3m"]))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("imports:upload")
    # La mutation de session a tout de même eu lieu avant le redirect.
    assert client_logged.session["import_period_mode"] == "3m"


# =============================================================================
# toggle_filter_account — masque/affiche un compte dans le graphe d'activité
# =============================================================================


@pytest.mark.django_db
def test_toggle_filter_account_htmx_returns_activity_section_partial(
    client_logged, account
):
    """HX → fragment _activity_section (dropdown filtre rouvert), inner HTML."""
    resp = client_logged.get(
        reverse("imports:toggle_filter_account", args=[str(account.id)]), **_HX
    )
    assert resp.status_code == 200
    assert "imports/partials/_activity_section.html" in {t.name for t in resp.templates}
    assert b"<!DOCTYPE html>" not in resp.content
    # Le compte a bien été ajouté à la blacklist session.
    assert account.id in client_logged.session["import_filter_accounts_hidden"]


@pytest.mark.django_db
def test_toggle_filter_account_non_htmx_redirects_to_upload(client_logged, account):
    """Requête nue → redirect vers imports:upload (PRG fallback)."""
    resp = client_logged.get(
        reverse("imports:toggle_filter_account", args=[str(account.id)])
    )
    assert resp.status_code == 302
    assert resp["Location"] == reverse("imports:upload")
    assert account.id in client_logged.session["import_filter_accounts_hidden"]

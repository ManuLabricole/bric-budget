"""
tests/patrimoine/test_navigation.py — coquille navigable patrimoine (vues + sidebar).

Couvre :
  - auth requise (redirect login si anonyme)
  - page classe fonctionnelle → 200 + listing des comptes de l'utilisateur
  - IDOR : un compte d'un autre user n'apparaît jamais (SR-001)
  - seuls les comptes du bon account_type sont listés
  - classe SOON → 200 (jamais 404) + badge SOON, pas de listing
  - slug inconnu → 404
  - toggle sidebar → flippe le booléen de session (PRG, 204)
  - context processor → injecte asset_classes + slug actif
  - asset_class enrichie : chart_json + dist_json + période + stacked (toggle)
"""

import pytest
from django.urls import reverse

from patrimoine.context_processors import SIDEBAR_SESSION_KEY

# --- fixtures locales (en plus de conftest.py) -------------------------------


@pytest.fixture
def savings_account(db, chf_institution, user):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=chf_institution,
        name="CHF Livret",
        account_type="savings",
        currency="CHF",
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="intrus@test.ch", password="pass")


@pytest.fixture
def other_user_account(db, chf_institution, other_user):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=chf_institution,
        name="Compte de l'intrus",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(other_user)
    return acc


# --- auth --------------------------------------------------------------------


@pytest.mark.django_db
def test_asset_class_page_requires_auth(client):
    url = reverse("patrimoine:asset_class", args=["comptes-courants"])
    resp = client.get(url)
    assert resp.status_code == 302
    assert "/login" in resp["Location"] or "/accounts/login" in resp["Location"]


# --- page fonctionnelle + IDOR ----------------------------------------------


@pytest.mark.django_db
def test_functional_page_lists_user_accounts(client, user, chf_account):
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["comptes-courants"])
    resp = client.get(url)
    assert resp.status_code == 200
    assert chf_account.name in resp.content.decode()


@pytest.mark.django_db
def test_idor_other_user_account_hidden(client, user, chf_account, other_user_account):
    """Un compte dont l'utilisateur n'est pas membre ne doit jamais apparaître."""
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["comptes-courants"])
    resp = client.get(url)
    body = resp.content.decode()
    assert chf_account.name in body
    assert other_user_account.name not in body


@pytest.mark.django_db
def test_page_filters_by_account_type(client, user, chf_account, savings_account):
    """La page comptes-courants ne liste pas les livrets (mauvais account_type)."""
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["comptes-courants"])
    resp = client.get(url)
    body = resp.content.decode()
    assert chf_account.name in body
    assert savings_account.name not in body


@pytest.mark.django_db
def test_inactive_account_hidden(client, user, chf_account):
    """Un compte désactivé n'apparaît pas dans le listing."""
    chf_account.is_active = False
    chf_account.save()
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["comptes-courants"])
    resp = client.get(url)
    assert chf_account.name not in resp.content.decode()


# --- SOON & 404 --------------------------------------------------------------


@pytest.mark.django_db
def test_soon_class_renders_not_404(client, user):
    """Une classe non fonctionnelle rend une page SOON, jamais une 404."""
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["crypto"])
    resp = client.get(url)
    assert resp.status_code == 200
    assert "SOON" in resp.content.decode()


@pytest.mark.django_db
def test_unknown_slug_returns_404(client, user):
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["slug-bidon"])
    resp = client.get(url)
    assert resp.status_code == 404


# --- toggle sidebar ----------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_toggle_persists_checkbox_state(client, user):
    """
    Fire-and-forget : 204 sans contenu. L'état session reflète l'état RÉEL de la
    checkbox (champ `open` présent = cochée), pas une simple inversion.
    """
    client.force_login(user)
    url = reverse("patrimoine:sidebar_toggle")

    # Checkbox cochée → `open` envoyé → session True.
    resp = client.post(url, {"open": "on"})
    assert resp.status_code == 204
    assert resp.content == b""
    assert client.session.get(SIDEBAR_SESSION_KEY) is True

    # Checkbox décochée → `open` absent → session False.
    resp2 = client.post(url, {})
    assert resp2.status_code == 204
    assert client.session.get(SIDEBAR_SESSION_KEY) is False


@pytest.mark.django_db
def test_sidebar_toggle_rejects_get(client, user):
    client.force_login(user)
    url = reverse("patrimoine:sidebar_toggle")
    resp = client.get(url)
    assert resp.status_code == 405  # require_POST


# --- page bilan (overview) ---------------------------------------------------


@pytest.mark.django_db
def test_overview_requires_auth(client):
    resp = client.get(reverse("patrimoine:overview"))
    assert resp.status_code == 302


@pytest.mark.django_db
def test_overview_renders_and_expands_section(client, user):
    """La page bilan rend en 200 (SOON) et déplie la section dans la sidebar."""
    client.force_login(user)
    resp = client.get(reverse("patrimoine:overview"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Patrimoine brut" in body
    # Atterrir sur le bilan force le dépliement (sous-items visibles).
    assert client.session.get(SIDEBAR_SESSION_KEY) is True
    assert "Comptes courants" in body


@pytest.mark.django_db
def test_overview_highlights_label_not_subitem(client, user):
    """Sur le bilan, le label Patrimoine est actif ; aucun sous-item ne l'est."""
    client.force_login(user)
    resp = client.get(reverse("patrimoine:overview"))
    assert resp.context["patrimoine_on_overview"] is True
    assert resp.context["active_asset_class_slug"] is None


# --- context processor -------------------------------------------------------


@pytest.mark.django_db
def test_context_processor_injects_asset_classes(client, user, chf_account):
    """asset_classes est disponible dans le template (sidebar) + slug actif marqué."""
    client.force_login(user)
    url = reverse("patrimoine:asset_class", args=["comptes-courants"])
    resp = client.get(url)
    # Le label de chaque classe doit apparaître dans la sidebar rendue.
    body = resp.content.decode()
    assert "Comptes courants" in body
    assert "Livrets" in body
    # La classe active est dans le contexte.
    assert resp.context["active_asset_class_slug"] == "comptes-courants"


# --- asset_class enrichie : graphe + période + stacked -----------------------

# Clés de session (miroir de views/asset_class.py — changement ici = changer là-bas).
_PERIOD_KEY = "patrimoine_ac_period_comptes-courants"
_STACKED_KEY = "patrimoine_ac_stacked_comptes-courants"
_AC_URL = "patrimoine:asset_class"
_PERIOD_URL = "patrimoine:set_asset_class_period"
_STACKED_URL = "patrimoine:set_asset_class_stacked"


@pytest.mark.django_db
def test_asset_class_context_has_chart_and_dist_json(client, user, chf_account):
    """La page enrichie expose chart_json (courbe) et dist_json (distribution)."""
    client.force_login(user)
    resp = client.get(reverse(_AC_URL, args=["comptes-courants"]))
    assert resp.status_code == 200
    assert "chart_json" in resp.context
    assert "dist_json" in resp.context


@pytest.mark.django_db
def test_asset_class_default_period_is_1m(client, user, chf_account):
    client.force_login(user)
    resp = client.get(reverse(_AC_URL, args=["comptes-courants"]))
    assert resp.context["period"] == "1m"


@pytest.mark.django_db
def test_asset_class_stacked_default_true(client, user, chf_account):
    client.force_login(user)
    resp = client.get(reverse(_AC_URL, args=["comptes-courants"]))
    assert resp.context["stacked"] is True


# --- set_asset_class_period --------------------------------------------------


@pytest.mark.django_db
def test_set_asset_class_period_requires_post(client, user):
    client.force_login(user)
    resp = client.get(reverse(_PERIOD_URL, args=["comptes-courants", "3m"]))
    assert resp.status_code == 405


@pytest.mark.django_db
def test_set_asset_class_period_persists_in_session(client, user, chf_account):
    client.force_login(user)
    client.post(reverse(_PERIOD_URL, args=["comptes-courants", "3m"]))
    assert client.session.get(_PERIOD_KEY) == "3m"


@pytest.mark.django_db
def test_set_asset_class_period_invalid_ignored(client, user, chf_account):
    """Une période inconnue ne doit pas écraser la valeur déjà en session."""
    client.force_login(user)
    session = client.session
    session[_PERIOD_KEY] = "1m"
    session.save()
    client.post(reverse(_PERIOD_URL, args=["comptes-courants", "bidon"]))
    assert client.session.get(_PERIOD_KEY) == "1m"


@pytest.mark.django_db
def test_set_asset_class_period_htmx_returns_partial(client, user, chf_account):
    """Avec HX-Request, la vue retourne le partial (pas la page complète)."""
    client.force_login(user)
    resp = client.post(
        reverse(_PERIOD_URL, args=["comptes-courants", "1m"]),
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" not in resp.content


@pytest.mark.django_db
def test_set_asset_class_period_non_htmx_redirects(client, user, chf_account):
    """Sans HX-Request (PRG fallback), la vue redirige vers la page classe."""
    client.force_login(user)
    resp = client.post(reverse(_PERIOD_URL, args=["comptes-courants", "1m"]))
    assert resp.status_code == 302


# --- set_asset_class_stacked -------------------------------------------------


@pytest.mark.django_db
def test_set_asset_class_stacked_requires_post(client, user):
    client.force_login(user)
    resp = client.get(reverse(_STACKED_URL, args=["comptes-courants"]))
    assert resp.status_code == 405


@pytest.mark.django_db
def test_set_asset_class_stacked_persists_false(client, user, chf_account):
    """Envoyer stacked=0 → False en session (mode standard)."""
    client.force_login(user)
    client.post(reverse(_STACKED_URL, args=["comptes-courants"]), {"stacked": "0"})
    assert client.session.get(_STACKED_KEY) is False


@pytest.mark.django_db
def test_set_asset_class_stacked_persists_true(client, user, chf_account):
    client.force_login(user)
    client.post(reverse(_STACKED_URL, args=["comptes-courants"]), {"stacked": "1"})
    assert client.session.get(_STACKED_KEY) is True


@pytest.mark.django_db
def test_set_asset_class_stacked_htmx_returns_partial(client, user, chf_account):
    client.force_login(user)
    resp = client.post(
        reverse(_STACKED_URL, args=["comptes-courants"]),
        {"stacked": "1"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" not in resp.content


@pytest.mark.django_db
def test_set_asset_class_stacked_non_htmx_redirects(client, user, chf_account):
    client.force_login(user)
    resp = client.post(
        reverse(_STACKED_URL, args=["comptes-courants"]), {"stacked": "1"}
    )
    assert resp.status_code == 302

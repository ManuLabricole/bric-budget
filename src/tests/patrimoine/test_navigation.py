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
def test_sidebar_toggle_flips_session(client, user):
    client.force_login(user)
    url = reverse("patrimoine:sidebar_toggle")

    # Premier POST : False → True. Renvoie le partial nav re-rendu.
    resp = client.post(url)
    assert resp.status_code == 200
    assert client.session.get(SIDEBAR_SESSION_KEY) is True
    body = resp.content.decode()
    assert 'id="patrimoine-nav"' in body
    # Déplié → les sous-items sont présents.
    assert "Comptes courants" in body

    # Second POST : True → False. Sous-items masqués.
    resp2 = client.post(url)
    assert client.session.get(SIDEBAR_SESSION_KEY) is False
    assert "Comptes courants" not in resp2.content.decode()


@pytest.mark.django_db
def test_sidebar_toggle_preserves_active_highlight(client, user):
    """Le toggle ne change pas la page : la surbrillance (hx-vals) est préservée."""
    client.force_login(user)
    resp = client.post(
        reverse("patrimoine:sidebar_toggle"),
        {"active_slug": "livrets", "on_overview": "0"},
    )
    body = resp.content.decode()
    # La ligne Livrets porte la classe active (text-gold) une fois re-rendue.
    assert "text-gold" in body


@pytest.mark.django_db
def test_sidebar_toggle_ignores_unknown_active_slug(client, user):
    """Un active_slug inconnu (injection potentielle) est ignoré, pas réinjecté tel quel."""
    client.force_login(user)
    resp = client.post(
        reverse("patrimoine:sidebar_toggle"),
        {"active_slug": 'evil"slug', "on_overview": "0"},
    )
    body = resp.content.decode()
    # La valeur fautive ne se retrouve pas dans hx-vals (bornée aux slugs connus).
    assert 'evil"slug' not in body
    assert "evil" not in body


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

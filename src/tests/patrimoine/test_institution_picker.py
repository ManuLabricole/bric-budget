"""
tests/patrimoine/test_institution_picker.py — picker « Compléter mon patrimoine ».

Vérifie : login requis · liste les institutions actives · filtre par ?q= ·
les inactives n'apparaissent pas. Réseau jamais touché (le post_save logo est
neutralisé par la garde globale de tests/conftest.py).
"""

import pytest
from django.urls import reverse

from accounts.models import Institution

# La vue est un endpoint HTMX (panel droit) : sans ce header elle redirige (pas de
# partial nu servi en navigation directe). Les tests de contenu doivent le fournir.
_HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def catalogue(db):
    Institution.objects.create(
        name="Yuh",
        slug="yuh",
        country="CH",
        default_currency="CHF",
        icon_slug="yuh",
        domain="yuh.ch",
    )
    Institution.objects.create(
        name="UBS",
        slug="ubs",
        country="CH",
        default_currency="CHF",
        icon_slug="ubs",
        domain="ubs.com",
    )
    Institution.objects.create(
        name="Vieille Banque",
        slug="vieille",
        country="FR",
        default_currency="EUR",
        is_active=False,
    )


@pytest.mark.django_db
def test_picker_requires_login(client):
    resp = client.get(reverse("patrimoine:institution_picker"))
    assert resp.status_code == 302
    assert "/login" in resp.url or "/connexion" in resp.url


@pytest.mark.django_db
def test_picker_direct_nav_redirects(client_logged, catalogue):
    """Navigation directe (sans HX-Request) → redirige vers le bilan, pas de partial nu."""
    resp = client_logged.get(reverse("patrimoine:institution_picker"))
    assert resp.status_code == 302
    assert resp.url == reverse("patrimoine:overview")


@pytest.mark.django_db
def test_picker_lists_active_institutions(client_logged, catalogue):
    resp = client_logged.get(reverse("patrimoine:institution_picker"), **_HX)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'id="institution-list"' in html
    assert "Yuh" in html
    assert "UBS" in html
    # Une institution inactive ne doit pas apparaître.
    assert "Vieille Banque" not in html


@pytest.mark.django_db
def test_picker_search_filters(client_logged, catalogue):
    resp = client_logged.get(
        reverse("patrimoine:institution_picker"), {"q": "yuh"}, **_HX
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Yuh" in html
    assert "UBS" not in html


@pytest.mark.django_db
def test_picker_search_empty_shows_message(client_logged, catalogue):
    resp = client_logged.get(
        reverse("patrimoine:institution_picker"), {"q": "zzzznope"}, **_HX
    )
    assert resp.status_code == 200
    assert "Aucune institution" in resp.content.decode()

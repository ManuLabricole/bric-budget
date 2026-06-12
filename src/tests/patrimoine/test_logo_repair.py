"""
tests/patrimoine/test_logo_repair.py — réparation manuelle d'un logo par URL (#128).

Vérifie le couple vue/UI : login requis, formulaire GET, POST succès (logo installé
+ ligne re-rendue), POST rejeté (422 + message). Le service logos.fetch_from_url est
monkeypatché (aucun réseau, aucun storage réel) — sa logique propre est couverte par
tests/services/test_logos.py.
"""

import pytest
from django.urls import reverse

from accounts.models import Institution

_HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def institution(db):
    return Institution.objects.create(
        name="ZKB", slug="zkb", country="CH", default_currency="CHF", icon_slug="zkb"
    )


def test_logo_form_requires_login(client, institution):
    url = reverse("patrimoine:institution_logo_form", args=[institution.slug])
    r = client.get(url, **_HX)
    assert r.status_code == 302  # redirection login


def test_logo_form_renders_inline_form(client_logged, institution):
    url = reverse("patrimoine:institution_logo_form", args=[institution.slug])
    r = client_logged.get(url, **_HX)
    assert r.status_code == 200
    assert b"logo_url" in r.content
    assert b"inst-row-zkb" in r.content


def test_logo_form_direct_navigation_redirects(client_logged, institution):
    # Sans header HX-Request → pas de partial nu servi, redirige vers le bilan.
    url = reverse("patrimoine:institution_logo_form", args=[institution.slug])
    r = client_logged.get(url)
    assert r.status_code == 302


def test_logo_repair_unknown_institution_404(client_logged):
    url = reverse("patrimoine:institution_logo_repair", args=["pas-une-banque"])
    r = client_logged.post(url, {"logo_url": "https://x.example/a.png"}, **_HX)
    assert r.status_code == 404


def test_logo_repair_rejects_non_https(client_logged, institution):
    url = reverse("patrimoine:institution_logo_repair", args=[institution.slug])
    r = client_logged.post(url, {"logo_url": "http://x.example/a.png"}, **_HX)
    assert r.status_code == 422
    assert b"https" in r.content.lower()


def test_logo_repair_success_rerenders_row(client_logged, institution, monkeypatch):
    from services import logos

    # fetch_from_url réussit → renvoie un nom stocké ; on simule aussi sa présence
    # dans le map résolu pour que la ligne re-rendue affiche le logo.
    monkeypatch.setattr(
        logos, "fetch_from_url", lambda url, slug: "icons/institutions/zkb.png"
    )
    monkeypatch.setattr(
        logos,
        "get_institution_icon_map",
        lambda: {"zkb": "/media/icons/institutions/zkb.png"},
    )
    url = reverse("patrimoine:institution_logo_repair", args=[institution.slug])
    r = client_logged.post(url, {"logo_url": "https://zkb.ch/logo.png"}, **_HX)
    assert r.status_code == 200
    assert b"inst-row-zkb" in r.content
    assert b"/media/icons/institutions/zkb.png" in r.content
    # logo résolu → plus de bouton réparation dans la ligne.
    assert b"logo_url" not in r.content


def test_logo_repair_service_failure_returns_422(
    client_logged, institution, monkeypatch
):
    from services import logos

    monkeypatch.setattr(logos, "fetch_from_url", lambda url, slug: None)
    url = reverse("patrimoine:institution_logo_repair", args=[institution.slug])
    r = client_logged.post(url, {"logo_url": "https://zkb.ch/logo.png"}, **_HX)
    assert r.status_code == 422
    assert b"logo_url" in r.content  # le formulaire est re-rendu pour réessayer

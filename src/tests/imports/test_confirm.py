"""
tests/imports/test_confirm.py

V1 — Tests des vues qui MUTENT côté imports :
  - import_confirm        : exécute l'import réel (POST)
  - import_create_account : crée un compte bancaire pendant import (POST)

Le happy path d'import_confirm n'est pas testé ici (nécessite un vrai CSV
parsable end-to-end → couvert par tests/integration/test_import_integration.py).
On teste les chemins d'erreur + l'auth.
"""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Institution


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="confirm@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def bank(db):
    return Institution.objects.create(
        name="Confirm Bank",
        slug="confirm-bank",
        country="CH",
        default_currency="CHF",
    )


# =============================================================================
# import_confirm — POST
# =============================================================================


@pytest.mark.django_db
def test_import_confirm_requires_login(client):
    r = client.post(reverse("imports:confirm"), HTTP_HOST="localhost")
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_import_confirm_without_session_returns_error(auth_client):
    """Pas de pending_import en session → render erreur 'Session expirée'."""
    r = auth_client.post(reverse("imports:confirm"), HTTP_HOST="localhost")
    # _error() retourne 200 avec un partial qui affiche le message d'erreur
    assert r.status_code == 200
    assert (
        "expir" in r.content.decode().lower()
        or "déjà confirmé" in r.content.decode().lower()
    )


@pytest.mark.django_db
def test_import_confirm_missing_tmp_file_returns_error(auth_client, tmp_path):
    """pending_import en session pointe vers un fichier inexistant → erreur + cleanup."""
    session = auth_client.session
    session["pending_import"] = {
        "filepath": str(tmp_path / "nonexistent.csv"),
        "filename": "nonexistent.csv",
        "file_hash": "abc",
        "institution_slug": "yuh",
    }
    session.save()
    r = auth_client.post(reverse("imports:confirm"), HTTP_HOST="localhost")
    assert r.status_code == 200
    assert "introuvable" in r.content.decode().lower()
    # La session a été cleanée
    assert "pending_import" not in auth_client.session


@pytest.mark.django_db
def test_import_confirm_get_method_not_allowed(auth_client):
    r = auth_client.get(reverse("imports:confirm"), HTTP_HOST="localhost")
    assert r.status_code == 405

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

from accounts.models import Account, Bank, CheckingAccount


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="confirm@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.login(email="confirm@t.ch", password="p")
    return c


@pytest.fixture
def bank(db):
    return Bank.objects.create(
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
        "bank_slug": "yuh",
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


# =============================================================================
# import_create_account — POST
# =============================================================================


@pytest.mark.django_db
def test_import_create_account_requires_login(client, bank):
    r = client.post(
        reverse("imports:create_account"),
        {
            "bank_slug": bank.slug,
            "account_name": "X",
            "account_type": "checking",
            "iban": "CH001",
        },
        HTTP_HOST="localhost",
    )
    assert r.status_code == 302


@pytest.mark.django_db
def test_import_create_account_missing_name_returns_error(auth_client, bank):
    r = auth_client.post(
        reverse("imports:create_account"),
        {
            "bank_slug": bank.slug,
            "account_name": "",
            "account_type": "checking",
            "iban": "CH001",
        },
        HTTP_HOST="localhost",
    )
    assert r.status_code == 200
    assert "obligatoire" in r.content.decode().lower()
    assert not Account.objects.filter(bank=bank).exists()


@pytest.mark.django_db
def test_import_create_account_missing_identifier_returns_error(auth_client, bank):
    """Ni IBAN ni contract_number → erreur."""
    r = auth_client.post(
        reverse("imports:create_account"),
        {
            "bank_slug": bank.slug,
            "account_name": "Compte sans ID",
            "account_type": "checking",
            "iban": "",
            "contract_number": "",
        },
        HTTP_HOST="localhost",
    )
    assert r.status_code == 200
    content = r.content.decode().lower()
    assert "identifiant" in content or "obligatoire" in content
    assert not Account.objects.filter(name="Compte sans ID").exists()


@pytest.mark.django_db
def test_import_create_account_invalid_type_returns_error(auth_client, bank):
    r = auth_client.post(
        reverse("imports:create_account"),
        {
            "bank_slug": bank.slug,
            "account_name": "Compte invalide",
            "account_type": "wrong_type",
            "iban": "CH001",
        },
        HTTP_HOST="localhost",
    )
    assert r.status_code == 200
    assert "invalide" in r.content.decode().lower()


@pytest.mark.django_db
def test_import_create_account_unknown_bank_returns_error(auth_client):
    r = auth_client.post(
        reverse("imports:create_account"),
        {
            "bank_slug": "bank-doesnt-exist",
            "account_name": "X",
            "account_type": "checking",
            "iban": "CH001",
        },
        HTTP_HOST="localhost",
    )
    assert r.status_code == 200
    assert "introuvable" in r.content.decode().lower()


@pytest.mark.django_db
def test_import_create_account_get_method_not_allowed(auth_client):
    r = auth_client.get(reverse("imports:create_account"), HTTP_HOST="localhost")
    assert r.status_code == 405


@pytest.mark.django_db
def test_import_create_account_success_creates_checking_account(auth_client, bank):
    """Happy path : crée Account + CheckingAccount (mais sans pending_import en session,
    la vue retourne erreur 'Session expirée' après création — c'est attendu pour ce test
    qui valide uniquement la mutation DB.)"""
    auth_client.post(
        reverse("imports:create_account"),
        {
            "bank_slug": bank.slug,
            "account_name": "Mon nouveau compte CH",
            "account_type": "checking",
            "iban": "CH9300762011623852957",
            "bic": "RAIFCH22",
            "currency": "CHF",
        },
        HTTP_HOST="localhost",
    )
    # L'Account doit être créé même si la session pending_import manque
    # (la fonction crée l'Account dans une transaction atomique, puis re-vérifie la session)
    acc = Account.objects.filter(name="Mon nouveau compte CH", bank=bank).first()
    assert acc is not None
    assert acc.account_type == "checking"
    assert CheckingAccount.objects.filter(account=acc).exists()

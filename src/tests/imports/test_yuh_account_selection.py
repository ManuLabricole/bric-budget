"""
tests/imports/test_yuh_account_selection.py — import Yuh avec sélection de compte (#118).

Yuh n'expose PAS d'identifiant de compte dans son CSV. Quand l'utilisateur a
plusieurs comptes Yuh, l'import affiche un picker. Régression réelle : le compte
choisi n'était pas mémorisé en session → import_confirm re-résolvait SANS forçage
→ AccountAmbiguous → import perdu (« part dans le vide »).

Ce test couvre tout le flux UI : upload → picker → select → confirm, et vérifie
que les transactions atterrissent bien sur LE compte choisi (et pas l'autre).
"""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounts.models import Account, CheckingAccount, Institution
from transactions.models import Transaction

YUH_FIXTURE = (
    Path(__file__).resolve().parents[1] / "connectors" / "fixtures" / "yuh_sample.csv"
)


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="yuh-sel@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def yuh_accounts(db, user):
    """Deux comptes Yuh actifs → force le picker (AccountAmbiguous)."""
    yuh = Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )
    accounts = []
    for name in ("Yuh courant", "Yuh épargne"):
        acc = Account.objects.create(
            institution=yuh,
            name=name,
            account_type=Account.AccountType.CHECKING,
            currency="CHF",
            is_active=True,
        )
        acc.members.add(user)
        CheckingAccount.objects.create(account=acc)
        accounts.append(acc)
    return accounts


@pytest.fixture
def storage(settings, tmp_path):
    """Stockage chiffré redirigé en tmp (pas de pollution de assets/private/)."""
    settings.IMPORT_STORAGE_ROOT = tmp_path / "imports"
    settings.IMPORT_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return settings


@pytest.mark.django_db
def test_yuh_import_with_picker_lands_on_chosen_account(
    auth_client, yuh_accounts, storage
):
    courant, epargne = yuh_accounts
    upload = SimpleUploadedFile(
        "yuh.csv", YUH_FIXTURE.read_bytes(), content_type="text/csv"
    )

    # 1. Upload → plusieurs comptes Yuh → picker (AccountAmbiguous).
    r1 = auth_client.post(
        reverse("imports:upload"), {"file": upload}, HTTP_HOST="localhost"
    )
    assert r1.status_code == 200
    # Le chemin "ambigu" stocke institution_slug en session (signal du picker).
    assert auth_client.session["pending_import"]["institution_slug"] == "yuh"

    # 2. Sélection du compte COURANT Yuh.
    r2 = auth_client.post(
        reverse("imports:select_account"),
        {"account_id": courant.pk},
        HTTP_HOST="localhost",
    )
    assert r2.status_code == 200
    # Cœur du fix : le compte choisi est mémorisé en session pour le confirm.
    assert auth_client.session["pending_import"]["forced_account_id"] == courant.pk

    # 3. Confirmation → import réel ; succès = HX-Redirect.
    r3 = auth_client.post(reverse("imports:confirm"), HTTP_HOST="localhost")
    assert r3.status_code == 200
    assert r3.headers.get("HX-Redirect")

    # Les transactions atterrissent sur le compte CHOISI (courant), pas l'épargne,
    # pas « dans le vide ».
    assert Transaction.objects.filter(account=courant).count() > 0
    assert Transaction.objects.filter(account=epargne).count() == 0

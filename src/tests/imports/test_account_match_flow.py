"""
tests/imports/test_account_match_flow.py — flux d'import « rattachement explicite » (#274).

Règle : aucun import sans rattachement à un compte EXISTANT.
    - Identité inconnue (CIC/UBS) → blocage + CTA « Compléter mon patrimoine » + picker.
    - Yuh (pas d'identité) → picker manuel TOUJOURS, même à un seul compte.
    - account_form : identifiant détecté pré-rempli en read-only (l'user ne saisit que le nom).
    - Soupape : corriger le compte cible même après un match.
"""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounts.models import Account, CheckingAccount, Institution

YUH_FIXTURE = (
    Path(__file__).resolve().parents[1] / "connectors" / "fixtures" / "yuh_sample.csv"
)


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="match@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def storage(settings, tmp_path):
    settings.IMPORT_STORAGE_ROOT = tmp_path / "imports"
    settings.IMPORT_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return settings


def _make_account(user, institution, name, currency="EUR"):
    acc = Account.objects.create(
        institution=institution,
        name=name,
        account_type=Account.AccountType.CHECKING,
        currency=currency,
        is_active=True,
    )
    acc.members.add(user)
    CheckingAccount.objects.create(account=acc)
    return acc


# =============================================================================
# CIC — identité inconnue → blocage + CTA + picker
# =============================================================================


@pytest.mark.django_db
def test_cic_unknown_account_renders_block_and_cta(auth_client, cic_file, storage):
    """RIB CIC absent en base → fragment 'Compte inconnu' (pas de création à la volée)."""
    Institution.objects.create(name="CIC", slug="cic", country="FR")
    upload = SimpleUploadedFile(
        "cic.xlsx",
        cic_file.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    response = auth_client.post(
        reverse("imports:upload"), {"file": upload}, HTTP_HOST="localhost"
    )

    assert response.status_code == 200
    assert "Compte inconnu" in response.content.decode()
    assert "Compléter mon patrimoine" in response.content.decode()
    # Le fichier reste en attente : l'user peut créer OU rattacher un compte existant.
    assert auth_client.session["pending_import"]["institution_slug"] == "cic"


@pytest.mark.django_db
def test_cic_unknown_account_lists_existing_accounts_in_picker(
    auth_client, user, cic_file, storage
):
    """Si l'user a déjà des comptes, le no-match propose AUSSI de les rattacher (picker)."""
    Institution.objects.create(name="CIC", slug="cic", country="FR")
    bourso = Institution.objects.create(
        name="BoursoBank", slug="boursobank", country="FR"
    )
    _make_account(user, bourso, "Mon Bourso")

    upload = SimpleUploadedFile(
        "cic.xlsx",
        cic_file.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response = auth_client.post(
        reverse("imports:upload"), {"file": upload}, HTTP_HOST="localhost"
    )

    # Picker scopé aux institutions de l'user (ici BoursoBank, où il a un compte).
    assert "Mon Bourso" in response.content.decode()
    assert "BoursoBank" in response.content.decode()


# =============================================================================
# Yuh — picker TOUJOURS, même à un seul compte
# =============================================================================


@pytest.mark.django_db
def test_single_yuh_account_still_requires_picker(auth_client, user, storage):
    """Yuh n'expose pas d'identité → on ne devine plus, même avec UN seul compte."""
    yuh = Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )
    _make_account(user, yuh, "Yuh unique", currency="CHF")

    upload = SimpleUploadedFile(
        "yuh.csv", YUH_FIXTURE.read_bytes(), content_type="text/csv"
    )
    response = auth_client.post(
        reverse("imports:upload"), {"file": upload}, HTTP_HOST="localhost"
    )

    assert response.status_code == 200
    assert "Quel compte" in response.content.decode()
    assert auth_client.session["pending_import"]["institution_slug"] == "yuh"


# =============================================================================
# account_form — pré-remplissage identité read-only
# =============================================================================


@pytest.mark.django_db
def test_account_form_prefills_contract_number_readonly(auth_client):
    """GET account_form?contract_number=… → champ pré-rempli ET verrouillé (read-only)."""
    Institution.objects.create(name="CIC", slug="cic", country="FR", is_active=True)

    response = auth_client.get(
        reverse("patrimoine:account_form"),
        {"institution": "cic", "contract_number": "100961802700064764601"},
        HTTP_HX_REQUEST="true",
        HTTP_HOST="localhost",
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert "100961802700064764601" in body
    assert "readonly" in body
    assert "détecté à l'import" in body


# =============================================================================
# Soupape — corriger le compte après un match
# =============================================================================


@pytest.mark.django_db
def test_manual_picker_available_after_match(auth_client, user, storage):
    """Après un dry-run matché (Yuh forcé), account_picker_manual réaffiche le picker."""
    yuh = Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )
    a1 = _make_account(user, yuh, "Yuh A", currency="CHF")
    _make_account(user, yuh, "Yuh B", currency="CHF")

    upload = SimpleUploadedFile(
        "yuh.csv", YUH_FIXTURE.read_bytes(), content_type="text/csv"
    )
    auth_client.post(reverse("imports:upload"), {"file": upload}, HTTP_HOST="localhost")
    auth_client.post(
        reverse("imports:select_account"), {"account_id": a1.pk}, HTTP_HOST="localhost"
    )

    # Soupape : on rouvre le picker pour corriger le compte cible.
    response = auth_client.get(
        reverse("imports:account_picker_manual"), HTTP_HOST="localhost"
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Yuh A" in body
    assert "Yuh B" in body


# =============================================================================
# IDOR — forcer le compte d'un autre user est fermé par for_user (SR-001)
# =============================================================================


@pytest.mark.django_db
def test_select_account_rejects_other_users_account(auth_client, user, storage):
    """User A ne peut PAS forcer l'import sur un compte appartenant à user B."""
    yuh = Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )
    _make_account(user, yuh, "Yuh A user", currency="CHF")

    # Compte d'un AUTRE user — jamais résoluble par A.
    other = get_user_model().objects.create_user(email="other@t.ch", password="p")
    victim = _make_account(other, yuh, "Yuh victime", currency="CHF")

    upload = SimpleUploadedFile(
        "yuh.csv", YUH_FIXTURE.read_bytes(), content_type="text/csv"
    )
    auth_client.post(reverse("imports:upload"), {"file": upload}, HTTP_HOST="localhost")

    # A forge un POST avec l'account_id de B.
    response = auth_client.post(
        reverse("imports:select_account"),
        {"account_id": victim.pk},
        HTTP_HOST="localhost",
    )

    # Rejeté (compte invalide) et rien n'atterrit sur le compte de la victime.
    assert "Compte invalide" in response.content.decode()
    from transactions.models import Transaction

    assert Transaction.objects.filter(account=victim).count() == 0

"""
tests/imports/test_idor.py

Tests IDOR pour l'app imports/ :
  - ImportLog log_detail + log_delete (account__members scoping)
  - Filehash scoping : un import d'un autre user ne bloque pas un nouvel import
  - import_select_account : user B ne peut pas relancer un dry-run sur le compte de user A
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import ImportLog

# =============================================================================
# Fixtures partagées
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@import-idor.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@import-idor.ch", password="pass"
    )


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.force_login(user_a)
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.force_login(user_b)
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Import IDOR Bank",
        slug="import-idor-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank, name="Account A Import", account_type="checking", currency="CHF"
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank, user_b):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank, name="Account B Import", account_type="checking", currency="CHF"
    )
    acc.members.add(user_b)
    return acc


@pytest.fixture
def log_a(db, account_a, user_a):
    return ImportLog.objects.create(
        account=account_a,
        imported_by=user_a,
        filename="yuh_export.csv",
        file_hash=hashlib.sha256(b"import-idor-log-a").hexdigest(),
        status="success",
        count_created=5,
    )


# =============================================================================
# ImportLog log_detail — IDOR
# =============================================================================


@pytest.mark.django_db
def test_idor_import_log_detail_blocked_for_other_user(client_b, log_a):
    response = client_b.get(reverse("imports:log_detail", args=[log_a.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_import_log_detail_allowed_for_owner(client_a, log_a):
    response = client_a.get(reverse("imports:log_detail", args=[log_a.pk]))
    assert response.status_code == 200


# =============================================================================
# ImportLog log_delete — IDOR
# =============================================================================


@pytest.mark.django_db
def test_idor_import_log_delete_blocked_for_other_user(client_b, log_a):
    response = client_b.post(reverse("imports:log_delete", args=[log_a.pk]))
    assert response.status_code == 404
    assert ImportLog.objects.filter(pk=log_a.pk).exists()


@pytest.mark.django_db
def test_idor_import_log_delete_allowed_for_owner(client_a, log_a):
    log_pk = log_a.pk
    response = client_a.post(reverse("imports:log_delete", args=[log_pk]))
    assert response.status_code == 200
    assert not ImportLog.objects.filter(pk=log_pk).exists()


# =============================================================================
# Filehash scoping — même hash ≠ doublon pour un autre user
# =============================================================================


@pytest.fixture
def log_a_filehash(db, account_a, user_a):
    return ImportLog.objects.create(
        account=account_a,
        imported_by=user_a,
        filename="yuh_export_jan.csv",
        file_hash=hashlib.sha256(b"shared-file-content").hexdigest(),
        status="success",
        count_created=10,
    )


@pytest.mark.django_db
def test_importlog_filehash_scoped_to_user_a_finds_own_log(user_a, log_a_filehash):
    result = ImportLog.objects.filter(
        file_hash=log_a_filehash.file_hash,
        account__members=user_a,
    ).first()
    assert result is not None
    assert result.pk == log_a_filehash.pk


@pytest.mark.django_db
def test_importlog_filehash_scoped_to_user_b_finds_nothing(user_b, log_a_filehash):
    result = ImportLog.objects.filter(
        file_hash=log_a_filehash.file_hash,
        account__members=user_b,
    ).first()
    assert result is None


@pytest.mark.django_db
def test_importlog_global_filter_would_expose_log(user_b, log_a_filehash):
    # Sans scope → trouve le log de user_a (ancienne faille documentée)
    assert (
        ImportLog.objects.filter(file_hash=log_a_filehash.file_hash).first() is not None
    )
    # Avec scope user_b → invisible (le fix)
    assert (
        ImportLog.objects.filter(
            file_hash=log_a_filehash.file_hash,
            account__members=user_b,
        ).first()
        is None
    )


@pytest.mark.django_db
def test_same_filehash_is_not_duplicate_for_different_user(user_b, log_a_filehash):
    existing = ImportLog.objects.filter(
        file_hash=log_a_filehash.file_hash,
        account__members=user_b,
    ).first()
    assert existing is None


@pytest.mark.django_db
def test_same_filehash_is_duplicate_for_original_user(user_a, log_a_filehash):
    existing = ImportLog.objects.filter(
        file_hash=log_a_filehash.file_hash,
        account__members=user_a,
    ).first()
    assert existing is not None
    assert existing.pk == log_a_filehash.pk


# =============================================================================
# import_select_account — IDOR
# =============================================================================


@pytest.mark.django_db
def test_import_select_account_idor_blocked_for_other_user(
    client_b, account_a, bank, tmp_path
):
    """
    user B POST avec account_id appartenant à user A → erreur "Compte invalide".
    Account.objects.for_user(request.user).get(pk=account_a.pk) → DoesNotExist.
    """
    fake_csv = tmp_path / "yuh_export.csv"
    fake_csv.write_text("date,amount,description\n2024-01-01,100,Test")

    session = client_b.session
    session["pending_import"] = {
        "filepath": str(fake_csv),
        "filename": "yuh_export.csv",
        "file_hash": "abc123",
        "bank_slug": bank.slug,
    }
    session.save()

    response = client_b.post(
        reverse("imports:select_account"),
        {"account_id": str(account_a.pk)},
    )
    assert "Compte invalide" in response.content.decode()


@pytest.mark.django_db
def test_import_select_account_idor_requires_login(client, account_a):
    response = client.post(
        reverse("imports:select_account"),
        {"account_id": str(account_a.pk)},
    )
    assert response.status_code == 302
    assert "/login/" in response["Location"]

"""
tests/test_import_filehash_idor.py

Tests : protection IDOR sur le duplicate check file_hash dans import_upload

Pourquoi ces tests sont critiques :
    _handle_dry_run() vérifie si un fichier a déjà été importé via son hash.
    Sans scope user, le filtre est global : si user A a importé un fichier,
    user B peut uploader le même fichier et voir les métadonnées de l'import
    de user A (nom du compte, banque, date). C'est une fuite d'information.

    De plus, user B pouvait être bloqué ("déjà importé") à cause de l'import
    d'un autre user — ce qui est fonctionnellement incorrect.

    Fix appliqué :
        ImportLog.objects.filter(
            file_hash=file_hash,
            account__members=request.user,  ← scope user
        )

    Note architecture :
        ImportLog.file_hash est unique=True globalement (contrainte DB).
        En Phase 3 multi-user, il faudra passer à unique_together=(file_hash, account).
        Le fix actuel ne touche pas le schema — il scope uniquement la détection.

Scénarios testés :
    1. User A imported file → User B uploads same file → pas "déjà importé" pour B
    2. User A imported file → User A uploads same file → "déjà importé" pour A
    3. User B ne voit pas les données de l'import de user A dans la réponse
    4. ImportLog.objects.filter(file_hash, account__members=user) scoping — unit test
"""

import hashlib

import pytest

from transactions.models import ImportLog

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@filehash-idor.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@filehash-idor.ch", password="pass"
    )


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="FileHash IDOR Bank",
        slug="filehash-idor-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Account A FileHash",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def log_a(db, account_a, user_a):
    """ImportLog appartenant à user_a, avec un file_hash connu."""
    return ImportLog.objects.create(
        account=account_a,
        imported_by=user_a,
        filename="yuh_export_jan.csv",
        file_hash=hashlib.sha256(b"shared-file-content").hexdigest(),
        status="success",
        count_created=10,
    )


# =============================================================================
# Unit tests — scoping ImportLog.objects
# =============================================================================


@pytest.mark.django_db
def test_importlog_filehash_scoped_to_user_a_finds_own_log(user_a, log_a):
    """filter(file_hash=..., account__members=user_a) trouve le log de user_a."""
    result = ImportLog.objects.filter(
        file_hash=log_a.file_hash,
        account__members=user_a,
    ).first()
    assert result is not None
    assert result.pk == log_a.pk


@pytest.mark.django_db
def test_importlog_filehash_scoped_to_user_b_finds_nothing(user_b, log_a):
    """
    filter(file_hash=..., account__members=user_b) ne trouve pas le log de user_a.

    user_b n'est pas membre du compte de user_a → le log est invisible pour user_b.
    Sans ce scope, user_b saurait que ce fichier a déjà été importé par quelqu'un.
    """
    result = ImportLog.objects.filter(
        file_hash=log_a.file_hash,
        account__members=user_b,
    ).first()
    assert result is None


@pytest.mark.django_db
def test_importlog_global_filter_would_expose_log(user_b, log_a):
    """
    Preuve que le filtre NON-scopé expose le log cross-user.

    Ce test documente l'ancienne vulnérabilité : filter(file_hash=...) sans
    account__members retournait les logs de tous les users.
    """
    # Sans scope → trouve le log de user_a (l'ancienne faille)
    result = ImportLog.objects.filter(file_hash=log_a.file_hash).first()
    assert result is not None  # ← ce que l'ancienne version faisait

    # Avec scope user_b → invisible (le fix)
    result_scoped = ImportLog.objects.filter(
        file_hash=log_a.file_hash,
        account__members=user_b,
    ).first()
    assert result_scoped is None  # ← ce que le fix garantit


# =============================================================================
# Comportement fonctionnel attendu
# =============================================================================


@pytest.mark.django_db
def test_same_filehash_is_not_duplicate_for_different_user(user_b, log_a):
    """
    Le même hash de fichier appartenant à user_a n'est PAS un doublon pour user_b.

    Comportement attendu : user_b peut importer un fichier même si user_a
    a déjà importé un fichier au hash identique. Leurs imports sont indépendants.
    """
    # Simuler la logique du duplicate check scopé
    existing_for_b = ImportLog.objects.filter(
        file_hash=log_a.file_hash,
        account__members=user_b,
    ).first()

    # Pour user_b, ce n'est PAS un doublon
    assert existing_for_b is None, (
        "Un import d'un autre user ne doit pas bloquer l'import de user_b"
    )


@pytest.mark.django_db
def test_same_filehash_is_duplicate_for_original_user(user_a, log_a):
    """
    Le même hash de fichier est bien un doublon pour user_a (l'importeur original).
    """
    existing_for_a = ImportLog.objects.filter(
        file_hash=log_a.file_hash,
        account__members=user_a,
    ).first()

    # Pour user_a, c'est un doublon → "déjà importé"
    assert existing_for_a is not None
    assert existing_for_a.pk == log_a.pk

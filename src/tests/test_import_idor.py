"""
tests/test_import_idor.py

Tests : protection IDOR sur les vues ImportLog de imports/views.py

Pourquoi ces tests sont critiques :
    import_log_delete détruit un ImportLog ET toutes ses transactions associées.
    Sans filtre user, user B peut supprimer l'historique d'import entier de user A
    en connaissant juste le PK (integer séquentiel, devinable par brute-force).

    Fix appliqué dans cette session :
        get_object_or_404(ImportLog.objects.filter(account__members=request.user), pk=pk)
    — même pattern que Transaction.objects.for_user(user).

Scénarios testés :
    1. import_log_detail  — user B → log de user A → 404
    2. import_log_detail  — user A → son propre log → 200
    3. import_log_delete  — user B → log de user A → 404, log non supprimé en DB
    4. import_log_delete  — user A → son propre log → 200, log supprimé en DB
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import ImportLog

# =============================================================================
# Fixtures
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
    c.login(email="usera@import-idor.ch", password="pass")
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.login(email="userb@import-idor.ch", password="pass")
    return c


@pytest.fixture
def account_a(db, user_a):
    """Compte appartenant à user_a uniquement."""
    from accounts.models import Account, Bank

    bank = Bank.objects.create(
        name="IDOR Import Bank A",
        slug="idor-import-bank-a",
        country="CH",
        default_currency="CHF",
    )
    acc = Account.objects.create(
        bank=bank,
        name="Account A Import",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def log_a(db, account_a, user_a):
    """ImportLog appartenant à user_a (via account_a)."""
    return ImportLog.objects.create(
        account=account_a,
        imported_by=user_a,
        filename="yuh_export.csv",
        file_hash=hashlib.sha256(b"import-idor-log-a").hexdigest(),
        status="success",
        count_created=5,
    )


# =============================================================================
# 1 & 2. import_log_detail
# =============================================================================


@pytest.mark.django_db
def test_idor_import_log_detail_blocked_for_other_user(client_b, log_a):
    """
    user B GET sur le log de user A → 404.
    Sans filtre account__members, cette vue retournait 200 pour n'importe quel PK.
    """
    response = client_b.get(reverse("imports:log_detail", args=[log_a.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_import_log_detail_allowed_for_owner(client_a, log_a):
    """user A peut accéder à son propre log → 200."""
    response = client_a.get(reverse("imports:log_detail", args=[log_a.pk]))
    assert response.status_code == 200


# =============================================================================
# 3 & 4. import_log_delete
# =============================================================================


@pytest.mark.django_db
def test_idor_import_log_delete_blocked_for_other_user(client_b, log_a):
    """
    user B POST delete sur le log de user A → 404.
    Le log ne doit PAS être supprimé.
    """
    response = client_b.post(reverse("imports:log_delete", args=[log_a.pk]))
    assert response.status_code == 404
    # Log toujours en DB
    assert ImportLog.objects.filter(pk=log_a.pk).exists()


@pytest.mark.django_db
def test_idor_import_log_delete_allowed_for_owner(client_a, log_a):
    """
    user A peut supprimer son propre log → log absent de la DB après.
    """
    log_pk = log_a.pk
    response = client_a.post(reverse("imports:log_delete", args=[log_pk]))
    # La vue fait HX-Redirect → 200 avec header
    assert response.status_code == 200
    # Log supprimé en DB
    assert not ImportLog.objects.filter(pk=log_pk).exists()

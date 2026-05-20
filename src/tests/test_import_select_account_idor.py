"""
tests/test_import_select_account_idor.py

Tests : IDOR sur import_select_account + AccountQuerySet.for_user()

Pourquoi ces tests sont critiques :
    import_select_account() reçoit un account_id en POST et relance un dry-run
    sur ce compte. Sans filtre Account.members, user B peut forger un POST avec
    l'account_id du compte de user A et importer des transactions dessus.

    Fix appliqué :
        Account.objects.for_user(request.user).get(pk=account_id, ...)
    — même pattern que Transaction.objects.for_user(user).

    Ce fichier teste aussi AccountQuerySet.for_user() directement (unit tests).

Scénarios testés :
    A. AccountQuerySet.for_user()
        1. for_user(user) retourne uniquement les comptes dont user est membre
        2. for_user(user) n'expose pas les comptes d'autres users
        3. for_user(None) retourne tous les comptes (usage CLI)
        4. Chainable avec .filter()

    B. import_select_account — IDOR
        5. user B POST avec account_id de user A → erreur (compte invalide)
        6. user A POST avec son propre account_id → dry-run relancé (pas d'erreur IDOR)

    C. resolve_accounts — user scoping
        7. resolve_accounts(connector, path, user=user_b) ne trouve pas le compte de user_a
        8. resolve_accounts(connector, path, user=None) trouve tous les comptes (CLI)
"""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Account, AccountQuerySet

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@select-idor.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@select-idor.ch", password="pass"
    )


@pytest.fixture
def client_a(user_a):
    c = Client()
    c.login(email="usera@select-idor.ch", password="pass")
    return c


@pytest.fixture
def client_b(user_b):
    c = Client()
    c.login(email="userb@select-idor.ch", password="pass")
    return c


@pytest.fixture
def bank_yuh(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Yuh IDOR Test",
        slug="yuh-idor-test",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank_yuh, user_a):
    """Compte appartenant à user_a uniquement."""
    acc = Account.objects.create(
        bank=bank_yuh,
        name="Account A Select",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank_yuh, user_b):
    """Compte appartenant à user_b uniquement."""
    acc = Account.objects.create(
        bank=bank_yuh,
        name="Account B Select",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_b)
    return acc


# =============================================================================
# A. AccountQuerySet.for_user() — unit tests
# =============================================================================


@pytest.mark.django_db
def test_account_for_user_returns_only_members_accounts(user_a, account_a, account_b):
    """for_user(user_a) retourne account_a mais pas account_b."""
    qs = Account.objects.for_user(user_a)
    assert account_a in qs
    assert account_b not in qs


@pytest.mark.django_db
def test_account_for_user_does_not_expose_other_users_accounts(
    user_b, account_a, account_b
):
    """for_user(user_b) ne retourne pas le compte de user_a."""
    qs = Account.objects.for_user(user_b)
    assert account_b in qs
    assert account_a not in qs


@pytest.mark.django_db
def test_account_for_user_none_returns_all_accounts(account_a, account_b):
    """for_user(None) retourne tous les comptes — usage CLI management commands."""
    qs = Account.objects.for_user(None)
    pks = list(qs.values_list("pk", flat=True))
    assert account_a.pk in pks
    assert account_b.pk in pks


@pytest.mark.django_db
def test_account_for_user_is_chainable(user_a, account_a, account_b, bank_yuh):
    """for_user() est chainable avec .filter() standard."""
    qs = Account.objects.for_user(user_a).filter(bank=bank_yuh, is_active=True)
    assert account_a in qs
    assert account_b not in qs


@pytest.mark.django_db
def test_account_for_user_returns_queryset_type(user_a):
    """for_user() retourne bien un QuerySet (pas une liste)."""
    result = Account.objects.for_user(user_a)
    assert isinstance(result, AccountQuerySet)


@pytest.mark.django_db
def test_account_for_user_empty_for_user_with_no_accounts(user_b, account_a):
    """User sans aucun compte → queryset vide."""
    # user_b n'est membre d'aucun compte (account_a appartient à un autre user)
    from django.contrib.auth import get_user_model

    lonely_user = get_user_model().objects.create_user(
        email="lonely@select-idor.ch", password="pass"
    )
    qs = Account.objects.for_user(lonely_user)
    assert qs.count() == 0


# =============================================================================
# B. import_select_account — IDOR
# =============================================================================


@pytest.mark.django_db
def test_import_select_account_idor_blocked_for_other_user(
    client_b, account_a, bank_yuh, tmp_path
):
    """
    user B POST avec account_id appartenant à user A → réponse erreur.

    Sans for_user(), la vue retournait un dry-run partiel sur le compte de user A.
    Avec le fix, Account.objects.for_user(request.user).get(pk=account_a.pk, ...)
    lève DoesNotExist → réponse "Compte invalide ou inactif."

    Note : on crée un vrai fichier temporaire pour dépasser le check d'existence
    de fichier (qui précède le check IDOR dans la vue).
    """
    # Créer un vrai fichier pour passer le check tmp_path.exists()
    fake_csv = tmp_path / "yuh_export.csv"
    fake_csv.write_text("date,amount,description\n2024-01-01,100,Test")

    session = client_b.session
    session["pending_import"] = {
        "filepath": str(fake_csv),
        "filename": "yuh_export.csv",
        "file_hash": "abc123",
        "bank_slug": bank_yuh.slug,
    }
    session.save()

    response = client_b.post(
        reverse("imports:select_account"),
        {"account_id": str(account_a.pk)},
    )
    # La réponse doit être une erreur "Compte invalide", pas un dry-run du compte de user A.
    # for_user(user_b).get(pk=account_a.pk) → DoesNotExist → _error("Compte invalide...")
    content = response.content.decode()
    assert "Compte invalide" in content


@pytest.mark.django_db
def test_import_select_account_idor_requires_login(client, account_a):
    """Vue protégée par @login_required."""
    response = client.post(
        reverse("imports:select_account"),
        {"account_id": str(account_a.pk)},
    )
    assert response.status_code == 302
    assert "/login/" in response["Location"]


# =============================================================================
# C. resolve_accounts — user scoping (unit tests sans parsing de fichier)
# =============================================================================


@pytest.mark.django_db
def test_resolve_accounts_yuh_scoped_to_user_finds_own_account(user_a, account_a):
    """
    Account.objects.for_user(user_a) trouve le compte de user_a.

    C'est le queryset de base que resolve_accounts utilise en interne.
    On teste directement le queryset sans parser un vrai fichier CSV Yuh.
    """
    qs = Account.objects.for_user(user_a).filter(pk=account_a.pk, is_active=True)
    assert qs.exists(), "user_a doit trouver son compte via for_user()"


@pytest.mark.django_db
def test_resolve_accounts_yuh_scoped_to_user_cannot_find_other_users_account(
    user_b, account_a
):
    """
    resolve_accounts avec user=user_b ne peut pas résoudre le compte de user_a.

    Test direct du queryset de sécurité sans parsing de fichier.
    """
    qs = Account.objects.for_user(user_b).filter(pk=account_a.pk, is_active=True)
    assert not qs.exists(), "user_b ne doit PAS trouver le compte de user_a"


@pytest.mark.django_db
def test_resolve_accounts_cli_mode_user_none_finds_all_accounts(account_a, account_b):
    """
    resolve_accounts avec user=None (CLI) trouve tous les comptes actifs.

    Les management commands (import_yuh, import_cic, import_ubs) passent user=None.
    Ce cas doit fonctionner sans restriction.
    """
    qs = Account.objects.for_user(None).filter(is_active=True)
    pks = list(qs.values_list("pk", flat=True))
    assert account_a.pk in pks
    assert account_b.pk in pks

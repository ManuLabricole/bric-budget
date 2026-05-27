"""
tests/accounts/test_members.py

Tests : Account.members M2M + TransactionQuerySet.for_user() + AccountQuerySet.for_user()

Invariant de sécurité fondamental : sans for_user(), un user voit les données de tous
les comptes, même ceux dont il n'est pas membre.
"""

import hashlib

import pytest

from accounts.models import Account, AccountQuerySet
from transactions.models import Category, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@accounts-test.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@accounts-test.ch", password="pass"
    )


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Accounts Test Bank",
        slug="accounts-test-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    acc = Account.objects.create(
        bank=bank, name="Compte A", account_type="checking", currency="CHF"
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank, user_b):
    acc = Account.objects.create(
        bank=bank, name="Compte B", account_type="checking", currency="CHF"
    )
    acc.members.add(user_b)
    return acc


@pytest.fixture
def account_joint(db, bank, user_a, user_b):
    acc = Account.objects.create(
        bank=bank, name="Compte joint", account_type="checking", currency="CHF"
    )
    acc.members.add(user_a, user_b)
    return acc


@pytest.fixture
def cat_revenus(db):
    return Category.objects.create(
        name="Revenus test",
        slug="revenus-test-members",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


def make_tx(account, label, seed=None):
    return Transaction.objects.create(
        account=account,
        date="2026-01-15",
        amount=-10,
        currency="CHF",
        amount_chf=-10,
        description_raw=label,
        display_name=label,
        import_hash=hashlib.sha256(
            f"members-test:{seed or label}".encode()
        ).hexdigest(),
    )


# =============================================================================
# A. TransactionQuerySet.for_user()
# =============================================================================


@pytest.mark.django_db
def test_for_user_returns_own_transactions(user_a, account_a):
    tx = make_tx(account_a, "TX USER A")
    assert tx in Transaction.objects.for_user(user_a)


@pytest.mark.django_db
def test_for_user_excludes_other_users_transactions(user_a, user_b, account_b):
    make_tx(account_b, "TX USER B")
    assert Transaction.objects.for_user(user_a).count() == 0


@pytest.mark.django_db
def test_for_user_joint_account_both_members_see_transactions(
    user_a, user_b, account_joint
):
    tx = make_tx(account_joint, "TX JOINT")
    assert tx in Transaction.objects.for_user(user_a)
    assert tx in Transaction.objects.for_user(user_b)


@pytest.mark.django_db
def test_for_user_isolation_mixed_accounts(user_a, account_a, account_b):
    tx_a = make_tx(account_a, "TX A", seed="iso-a")
    tx_b = make_tx(account_b, "TX B", seed="iso-b")
    qs = Transaction.objects.for_user(user_a)
    assert tx_a in qs
    assert tx_b not in qs


@pytest.mark.django_db
def test_budget_index_user_without_account_sees_no_transactions(
    user_a, account_b, cat_revenus
):
    make_tx(account_b, "TX B INVISIBLE")
    assert Transaction.objects.for_user(user_a).count() == 0


@pytest.mark.django_db
def test_budget_index_member_sees_own_transactions(user_a, account_a):
    tx = make_tx(account_a, "TX A VISIBLE")
    qs = Transaction.objects.for_user(user_a)
    assert tx in qs
    assert qs.count() == 1


# =============================================================================
# B. AccountQuerySet.for_user()
# =============================================================================


@pytest.mark.django_db
def test_account_for_user_returns_only_members_accounts(user_a, account_a, account_b):
    qs = Account.objects.for_user(user_a)
    assert account_a in qs
    assert account_b not in qs


@pytest.mark.django_db
def test_account_for_user_does_not_expose_other_users_accounts(
    user_b, account_a, account_b
):
    qs = Account.objects.for_user(user_b)
    assert account_b in qs
    assert account_a not in qs


@pytest.mark.django_db
def test_account_for_user_none_returns_all_accounts(account_a, account_b):
    pks = list(Account.objects.for_user(None).values_list("pk", flat=True))
    assert account_a.pk in pks
    assert account_b.pk in pks


@pytest.mark.django_db
def test_account_for_user_is_chainable(user_a, account_a, account_b, bank):
    qs = Account.objects.for_user(user_a).filter(bank=bank, is_active=True)
    assert account_a in qs
    assert account_b not in qs


@pytest.mark.django_db
def test_account_for_user_returns_queryset_type(user_a):
    assert isinstance(Account.objects.for_user(user_a), AccountQuerySet)


@pytest.mark.django_db
def test_account_for_user_empty_for_user_with_no_accounts(account_a):
    from django.contrib.auth import get_user_model

    lonely = get_user_model().objects.create_user(
        email="lonely@accounts-test.ch", password="pass"
    )
    assert Account.objects.for_user(lonely).count() == 0


# =============================================================================
# C. resolve_accounts — scoping par user (queryset direct, sans parsing de fichier)
# =============================================================================


@pytest.mark.django_db
def test_resolve_accounts_scoped_to_user_finds_own_account(user_a, account_a):
    qs = Account.objects.for_user(user_a).filter(pk=account_a.pk, is_active=True)
    assert qs.exists()


@pytest.mark.django_db
def test_resolve_accounts_scoped_to_user_cannot_find_other_users_account(
    user_b, account_a
):
    qs = Account.objects.for_user(user_b).filter(pk=account_a.pk, is_active=True)
    assert not qs.exists()


@pytest.mark.django_db
def test_resolve_accounts_cli_mode_user_none_finds_all_accounts(account_a, account_b):
    pks = list(
        Account.objects.for_user(None)
        .filter(is_active=True)
        .values_list("pk", flat=True)
    )
    assert account_a.pk in pks
    assert account_b.pk in pks

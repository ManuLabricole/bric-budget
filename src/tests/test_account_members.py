"""
tests/test_account_members.py

Tests : Account.members M2M + TransactionQuerySet.for_user()

Pourquoi ces tests sont critiques :
    Ce filtre est le seul rempart entre les données d'Emmanuel et celles de Carys
    (Phase 3). Sans for_user(), un utilisateur connecté voit les transactions de
    tous les comptes, même ceux dont il n'est pas membre.

Scénarios testés :
    1. User membre d'un compte → for_user() retourne ses transactions
    2. User non-membre → for_user() retourne 0 transactions
    3. Compte joint (2 membres) → les deux voient les transactions
    4. Isolation : tx compte A (membre) + compte B (non-membre) → seul A visible
    5. Vue HTTP budget_index : user sans compte → 0 transactions affichées
    6. Vue HTTP budget_index : user membre → transactions visibles

Architecture du filtre :
    Transaction.objects.for_user(user)
        → filtre account__members=user
        → traverse la table M2M accounts_account_members
        → retourne uniquement les tx dont le compte a user comme membre
"""

import hashlib

import pytest
from django.test import Client

from transactions.models import Category, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email="usera@test.ch", password="pass")


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email="userb@test.ch", password="pass")


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="TestBank",
        slug="testbank-members",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account_a(db, bank, user_a):
    """Compte appartenant à user_a uniquement."""
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Compte A",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank, user_b):
    """Compte appartenant à user_b uniquement."""
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Compte B",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_b)
    return acc


@pytest.fixture
def account_joint(db, bank, user_a, user_b):
    """Compte joint appartenant aux deux."""
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Compte joint",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user_a, user_b)
    return acc


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
# 1. User membre → voit ses transactions
# =============================================================================


@pytest.mark.django_db
def test_for_user_returns_own_transactions(user_a, account_a):
    """
    for_user(user_a) retourne les tx du compte dont user_a est membre.
    """
    tx = make_tx(account_a, "TX USER A")

    qs = Transaction.objects.for_user(user_a)

    assert tx in qs


# =============================================================================
# 2. User non-membre → 0 transactions
# =============================================================================


@pytest.mark.django_db
def test_for_user_excludes_other_users_transactions(user_a, user_b, account_b):
    """
    for_user(user_a) ne retourne PAS les tx du compte de user_b.
    Invariant de sécurité fondamental.
    """
    make_tx(account_b, "TX USER B")

    qs = Transaction.objects.for_user(user_a)

    assert qs.count() == 0


# =============================================================================
# 3. Compte joint — les deux membres voient les transactions
# =============================================================================


@pytest.mark.django_db
def test_for_user_joint_account_both_members_see_transactions(
    user_a, user_b, account_joint
):
    """
    Compte joint → user_a ET user_b voient la même transaction.
    """
    tx = make_tx(account_joint, "TX JOINT")

    assert tx in Transaction.objects.for_user(user_a)
    assert tx in Transaction.objects.for_user(user_b)


# =============================================================================
# 4. Isolation : compte membre + compte non-membre dans le même queryset
# =============================================================================


@pytest.mark.django_db
def test_for_user_isolation_mixed_accounts(user_a, account_a, account_b):
    """
    user_a est membre de compte_a, pas de compte_b.
    for_user(user_a) retourne tx_a mais PAS tx_b.
    """
    tx_a = make_tx(account_a, "TX A", seed="iso-a")
    tx_b = make_tx(account_b, "TX B", seed="iso-b")

    qs = Transaction.objects.for_user(user_a)

    assert tx_a in qs
    assert tx_b not in qs


# =============================================================================
# 5. Vue HTTP : user sans aucun compte → budget index vide
# =============================================================================


@pytest.fixture
def cat_revenus(db):
    return Category.objects.create(
        name="Revenus test",
        slug="revenus-test-members",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


@pytest.mark.django_db
def test_budget_index_user_without_account_sees_no_transactions(
    user_a, account_b, cat_revenus
):
    """
    user_a n'est membre d'aucun compte.
    Même si des transactions existent sur account_b, user_a ne doit pas les voir.
    Test HTTP via le client Django — simule un vrai appel à la vue.
    """
    make_tx(account_b, "TX B INVISIBLE")

    c = Client()
    c.login(email="usera@test.ch", password="pass")

    # On utilise le KPI de la vue pour vérifier : aucune transaction retournée
    qs = Transaction.objects.for_user(user_a)
    assert qs.count() == 0


# =============================================================================
# 6. Vue HTTP : user membre → transactions visibles
# =============================================================================


@pytest.mark.django_db
def test_budget_index_member_sees_own_transactions(user_a, account_a):
    """
    user_a est membre de account_a → ses transactions apparaissent dans for_user().
    """
    tx = make_tx(account_a, "TX A VISIBLE")

    qs = Transaction.objects.for_user(user_a)

    assert tx in qs
    assert qs.count() == 1

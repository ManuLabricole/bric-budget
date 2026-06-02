"""
tests/services/conftest.py — Fixtures Django pour les tests de l'ImportService.

Ces fixtures créent des objets en base de données.
Elles nécessitent que PostgreSQL soit actif (make up) et que le paramètre
DJANGO_SETTINGS_MODULE soit configuré dans pyproject.toml.

pytest-django crée une base de test dédiée (test_bricbudget ou similaire)
et la supprime après la session. Chaque test s'exécute dans une transaction
qui est rollbackée à la fin → pas d'effets de bord entre tests.

Pourquoi des fixtures plutôt que des setUp Django ?
----------------------------------------------------
Les fixtures pytest sont composables et injectables par nom. Un test qui
a besoin d'un utilisateur + un compte CHF déclare : def test_xxx(user, chf_account)
sans hériter de TestCase ni implémenter de setUp. Plus lisible, plus isolé.
"""

import hashlib

import pytest

from connectors.base import TransactionDict

# =============================================================================
# Fixtures DB — Utilisateur + Comptes
# =============================================================================


@pytest.fixture
def user(db):
    """
    Utilisateur CustomUser minimal pour les imports.

    ImportService.run() prend imported_by=User pour créer l'ImportLog.
    On en a besoin dans tous les tests d'ImportService.

    'db' est une fixture pytest-django built-in : accorde l'accès lecture/écriture
    à la base de données pour la durée du test.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(email="test@bricbudget.ch", password="testpass")


@pytest.fixture
def chf_bank(db):
    """Banque CHF fictive pour les comptes de test."""
    from accounts.models import Bank

    return Bank.objects.create(
        name="Test Bank CHF",
        slug="test-bank-chf",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def eur_bank(db):
    """Banque EUR fictive pour les comptes de test."""
    from accounts.models import Bank

    return Bank.objects.create(
        name="Test Bank EUR",
        slug="test-bank-eur",
        country="FR",
        default_currency="EUR",
    )


@pytest.fixture
def chf_account(db, chf_bank):
    """
    Compte courant en CHF.

    Utilisé pour tester que amount_chf == amount (pas de conversion nécessaire).
    Pas de CheckingAccount associé → _load_cards() retourne {} (aucune carte).
    """
    from accounts.models import Account

    return Account.objects.create(
        bank=chf_bank,
        name="Test CHF Account",
        account_type="checking",
        currency="CHF",
    )


@pytest.fixture
def eur_account(db, eur_bank):
    """
    Compte courant en EUR.

    Utilisé pour tester le calcul de amount_chf via le taux de change.
    """
    from accounts.models import Account

    return Account.objects.create(
        bank=eur_bank,
        name="Test EUR Account",
        account_type="checking",
        currency="EUR",
    )


# =============================================================================
# Helper — Création de TransactionDict de test
# =============================================================================


def make_tx(
    seed: str,
    date: str = "2026-03-17",
    amount: float = -25.40,
    currency: str = "CHF",
    description_raw: str = "TEST SHOP LAUSANNE",
    display_name: str = "Test Shop Lausanne",
    merchant_name: str = "Test Shop",
) -> TransactionDict:
    """
    Crée un TransactionDict minimal pour les tests.

    'seed' garantit des import_hash distincts entre les appels :
    make_tx("a") et make_tx("b") produisent des hashes différents.

    Pourquoi ne pas utiliser un vrai connecteur ici ?
    → Les tests d'ImportService ne doivent pas dépendre du parsing.
       On injecte des données contrôlées pour tester le service en isolation.
    """
    import_hash = hashlib.sha1(
        f"test:{seed}".encode(), usedforsecurity=False
    ).hexdigest()
    return TransactionDict(
        date=date,
        time=None,
        amount=amount,
        currency=currency,
        description_raw=description_raw,
        display_name=display_name,
        merchant_name=merchant_name,
        card_last_four=None,
        import_hash=import_hash,
        balance_after=None,
    )


def make_file_hash(seed: str) -> str:
    """Génère un file_hash de test depuis une graine courte."""
    return hashlib.sha1(f"file:{seed}".encode(), usedforsecurity=False).hexdigest()

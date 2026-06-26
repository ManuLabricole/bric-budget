"""
tests/factories/ — Factories factory_boy par modèle (issue #194).

Fin de la duplication des fixtures DB (`user_a`/`bank`/`account`/`category` recopiés
entre les conftests budget/services/patrimoine). Un nouveau test crée ses données en
une ligne : `tx = TransactionFactory(account=AccountFactory(members=[user]))`.

Toutes les factories sont ré-exportées ici → import unique :
    from tests.factories import UserFactory, AccountFactory, CategoryFactory

Règles respectées :
    - SR-002 : montants en Decimal(str(...)), jamais Decimal(float).
    - SR-008 : IBAN/contrats GÉNÉRÉS (Sequence/Faker), jamais de vrai identifiant.
    - #213   : modèles owned → owner explicite (retrouvables via .for_user(owner)) ;
               SystemCategoryFactory pour le partagé (owner NULL).
"""

from .accounts import (
    AccountFactory,
    BalanceSnapshotFactory,
    CheckingAccountFactory,
    InstitutionFactory,
    SavingsAccountFactory,
)
from .categories import (
    CategorizationRuleFactory,
    CategoryFactory,
    SubCategoryFactory,
    SystemCategoryFactory,
)
from .transactions import TransactionFactory
from .users import UserFactory

__all__ = [
    "UserFactory",
    "InstitutionFactory",
    "AccountFactory",
    "CheckingAccountFactory",
    "SavingsAccountFactory",
    "BalanceSnapshotFactory",
    "CategoryFactory",
    "SystemCategoryFactory",
    "SubCategoryFactory",
    "CategorizationRuleFactory",
    "TransactionFactory",
]

"""
tests/transactions/test_user_deletion_cleanup.py — #203 (sécu).

Supprimer un user ne doit laisser AUCUNE donnée perso orpheline traitée comme
« système ». Avant #203, `Category.owner`/`SubCategory.owner` étaient en SET_NULL :
la suppression d'un user transformait ses lignes perso en lignes owner=NULL
(= système, partagées) → collisions de contraintes + exposition des données.

#203 passe ces deux FK en CASCADE (les deux autres modèles owned —
CategorizationRule, BudgetTarget — étaient déjà en CASCADE). Invariant prouvé ici :
- toutes les lignes perso owned d'un user disparaissent à sa suppression ;
- ses TRANSACTIONS survivent (category/subcategory=SET_NULL → passent à NULL),
  donc CASCADE n'est PAS une perte de données ;
- les données SYSTÈME et celles d'un AUTRE user ne sont pas touchées.
"""

from decimal import Decimal
from typing import cast

import pytest
from django.contrib.auth import get_user_model

from tests.factories.categories import (
    CategorizationRuleFactory,
    CategoryFactory,
    SubCategoryFactory,
    SystemCategoryFactory,
)
from tests.factories.transactions import TransactionFactory
from transactions.models import (
    BudgetTarget,
    CategorizationRule,
    Category,
    SubCategory,
    Transaction,
)


# factory_boy : `XFactory(...)` est typé comme la classe factory, pas le modèle
# (mypy ne suit pas le `_create`). Wrappers castés pour récupérer le bon type —
# même pattern que tests/integration/test_crossmodule_integration.py (#228).
def _cat(**kwargs: object) -> Category:
    return cast(Category, CategoryFactory(**kwargs))


def _sys_cat(**kwargs: object) -> Category:
    return cast(Category, SystemCategoryFactory(**kwargs))


def _subcat(**kwargs: object) -> SubCategory:
    return cast(SubCategory, SubCategoryFactory(**kwargs))


def _rule(**kwargs: object) -> CategorizationRule:
    return cast(CategorizationRule, CategorizationRuleFactory(**kwargs))


def _tx(**kwargs: object) -> Transaction:
    return cast(Transaction, TransactionFactory(**kwargs))


@pytest.fixture
def user_a(db):
    return get_user_model().objects.create_user(email="ua203@budget.ch", password="x")


@pytest.fixture
def user_b(db):
    return get_user_model().objects.create_user(email="ub203@budget.ch", password="x")


@pytest.mark.django_db
def test_deleting_user_removes_all_owned_perso_rows(user_a):
    """Les 4 modèles owned (Category/SubCategory/CategorizationRule/BudgetTarget)
    perso de l'user sont supprimés à sa suppression — aucun orphelin owner=NULL."""
    cat = _cat(owner=user_a)
    sub = _subcat(category=cat)  # owner suit la catégorie → user_a
    rule = _rule(category=cat)  # owner → user_a
    target = BudgetTarget.objects.create(
        category=cat, owner=user_a, amount=Decimal("500.00")
    )
    ids = (cat.pk, sub.pk, rule.pk, target.pk)

    user_a.delete()

    # Plus aucune des lignes perso (unscoped car manager fail-closed #213).
    assert not Category.objects.unscoped().filter(pk=ids[0]).exists()
    assert not SubCategory.objects.unscoped().filter(pk=ids[1]).exists()
    assert not CategorizationRule.objects.unscoped().filter(pk=ids[2]).exists()
    assert not BudgetTarget.objects.unscoped().filter(pk=ids[3]).exists()
    # Et zéro orphelin perso (owner NULL sur une ligne is_system=False).
    assert not Category.objects.unscoped().filter(is_system=False).exists()
    assert not SubCategory.objects.unscoped().filter(is_system=False).exists()


@pytest.mark.django_db
def test_deleting_user_removes_perso_subcategory_under_system_category(user_a):
    """Cas-fuite #118 : une sous-cat PERSO accrochée à une catégorie SYSTÈME.
    SET_NULL l'aurait laissée survivre orpheline (owner=NULL, sous une cat système)
    = traitée comme système. CASCADE la supprime ; la catégorie système survit."""
    system_cat = _sys_cat()
    perso_sub = _subcat(category=system_cat, owner=user_a, is_system=False)
    sub_pk, sys_pk = perso_sub.pk, system_cat.pk

    user_a.delete()

    assert not SubCategory.objects.unscoped().filter(pk=sub_pk).exists()
    assert Category.objects.unscoped().filter(pk=sys_pk).exists()  # système épargnée


@pytest.mark.django_db
def test_deleting_user_preserves_transactions_as_uncategorized(user_a):
    """CASCADE sur owner n'est PAS une perte de données : Transaction.category et
    .subcategory sont en SET_NULL → les tx survivent, recatégorisables."""
    cat = _cat(owner=user_a)
    sub = _subcat(category=cat)
    tx = _tx(category=cat, subcategory=sub)
    tx_pk = tx.pk

    user_a.delete()

    tx.refresh_from_db()
    assert Transaction.objects.filter(pk=tx_pk).exists()  # tx survit
    assert tx.category_id is None  # SET_NULL → recatégorisable
    assert tx.subcategory_id is None


@pytest.mark.django_db
def test_deleting_user_does_not_touch_system_or_other_user_data(user_a, user_b):
    """Supprimer user_a laisse intactes les catégories système ET les lignes perso
    de user_b — la cascade est strictement scopée à l'owner supprimé."""
    _sys_cat(slug="system-keep", name="System Keep")
    b_cat = _cat(owner=user_b, slug="b-cat")
    b_target = BudgetTarget.objects.create(
        category=b_cat, owner=user_b, amount=Decimal("300.00")
    )
    _cat(owner=user_a, slug="a-cat")

    user_a.delete()

    assert Category.objects.unscoped().filter(slug="system-keep").exists()
    assert Category.objects.unscoped().filter(pk=b_cat.pk).exists()
    assert BudgetTarget.objects.unscoped().filter(pk=b_target.pk).exists()
    assert not Category.objects.unscoped().filter(slug="a-cat").exists()

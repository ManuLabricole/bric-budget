"""
tests/transactions/test_owned_manager_fail_closed.py — #213

Contrat de la couche-2 ORM fail-closed (OwnedManager / OwnedQuerySet) :

    Model.objects.all()           → .none()  (FAIL-CLOSED : pas de scope = 0 ligne)
    Model.objects.for_user(user)  → système (owner NULL) OU perso (owner=user)
    Model.objects.unscoped()      → accès GLOBAL (seul bypass, grep-able)

ET garde-fou : les INTERNES Django (FK descriptor, reverse-FK) NE doivent PAS être
cassés par le default fail-closed (résolus via base_manager_name="_base").
"""

import pytest
from django.contrib.auth import get_user_model

from transactions.models import (
    BudgetTarget,
    CategorizationRule,
    Category,
    SubCategory,
)

User = get_user_model()


@pytest.fixture
def two_users(db):
    a = User.objects.create_user(email="owna@example.com", password="x")
    b = User.objects.create_user(email="ownb@example.com", password="x")
    return a, b


@pytest.fixture
def data(two_users):
    """Une catégorie système + une perso pour chaque user, + sous-cats/règles/targets."""
    a, b = two_users
    sys_cat = Category.objects.create(name="Système", slug="systeme", is_system=True)
    cat_a = Category.objects.create(name="PersoA", slug="perso-a", owner=a)
    cat_b = Category.objects.create(name="PersoB", slug="perso-b", owner=b)
    sub_sys = SubCategory.objects.create(category=sys_cat, name="SubSys", slug="subsys")
    sub_a = SubCategory.objects.create(
        category=sys_cat, name="SubA", slug="suba", owner=a
    )
    rule_a = CategorizationRule.objects.create(keyword="AAA", category=cat_a, owner=a)
    target_a = BudgetTarget.objects.create(category=sys_cat, owner=a, amount="10.00")
    return {
        "a": a,
        "b": b,
        "sys_cat": sys_cat,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "sub_sys": sub_sys,
        "sub_a": sub_a,
        "rule_a": rule_a,
        "target_a": target_a,
    }


# ---------------------------------------------------------------------------
# 1. FAIL-CLOSED : .objects.all()/.filter() nus → aucune ligne
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model", [Category, SubCategory, CategorizationRule, BudgetTarget]
)
def test_objects_all_is_fail_closed(data, model):
    """Un accès non scopé retourne .none(), JAMAIS la donnée (d'autrui ou système)."""
    assert model.objects.all().count() == 0
    assert list(model.objects.all()) == []
    assert model.objects.filter(pk__gt=0).count() == 0
    assert model.objects.exists() is False


# ---------------------------------------------------------------------------
# 2. unscoped() = bypass global
# ---------------------------------------------------------------------------


def test_unscoped_sees_everything(data):
    # 3 catégories au total (1 système + 2 perso) malgré le fail-closed sur objects.
    assert Category.objects.unscoped().count() == 3
    assert SubCategory.objects.unscoped().count() == 2
    assert CategorizationRule.objects.unscoped().count() == 1
    assert BudgetTarget.objects.unscoped().count() == 1


# ---------------------------------------------------------------------------
# 3. for_user inchangé : système (owner NULL) OU perso de ce user
# ---------------------------------------------------------------------------


def test_for_user_returns_system_or_mine(data):
    a, b = data["a"], data["b"]
    cats_a = set(Category.objects.for_user(a).values_list("slug", flat=True))
    cats_b = set(Category.objects.for_user(b).values_list("slug", flat=True))
    assert cats_a == {"systeme", "perso-a"}  # système + ma perso, PAS perso-b
    assert cats_b == {"systeme", "perso-b"}


def test_for_user_never_leaks_other_user_perso(data):
    b = data["b"]
    # La sous-cat perso de A (sub_a) et la règle de A ne sont jamais visibles par B.
    assert not SubCategory.objects.for_user(b).filter(pk=data["sub_a"].pk).exists()
    assert (
        not CategorizationRule.objects.for_user(b).filter(pk=data["rule_a"].pk).exists()
    )
    # La sous-cat système reste visible par tous.
    assert SubCategory.objects.for_user(b).filter(pk=data["sub_sys"].pk).exists()


# ---------------------------------------------------------------------------
# 4. GARDE-FOU : les internes Django ne sont PAS cassés par le fail-closed
# ---------------------------------------------------------------------------


def test_fk_descriptor_still_resolves(data):
    """sub.category (FK descriptor forward) passe par le base manager (_base) →
    résout l'objet parent malgré le fail-closed du default manager.
    C'est LE garde-fou : sans base_manager_name="_base", cet accès casserait."""
    sub = SubCategory.objects.unscoped().get(pk=data["sub_a"].pk)
    assert sub.category == data["sys_cat"]


def test_reverse_fk_related_manager_is_also_fail_closed(data):
    """cat.subcategories.all() (related manager applicatif) hérite du default manager
    (OwnedManager) → AUSSI fail-closed. C'est VOULU : un accès reverse-FK nu dans une
    vue/template ne fuit plus ; il faut scoper explicitement (for_user/unscoped).

    NB : ceci ne casse PAS les internes Django (prefetch_related avec un queryset
    scopé, FK forward) — seulement le `.all()/.filter()` nu côté application."""
    sys_cat = Category.objects.unscoped().get(pk=data["sys_cat"].pk)
    assert sys_cat.subcategories.all().count() == 0
    # Le scope explicite via le manager du modèle lié reste la bonne porte :
    assert (
        SubCategory.objects.unscoped().filter(category=sys_cat).count() == 2
    )  # global
    a = data["a"]
    # système (sub_sys) + ma perso (sub_a) → 2 ; jamais la perso d'un autre.
    assert SubCategory.objects.for_user(a).filter(category=sys_cat).count() == 2

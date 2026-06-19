"""
tests/transactions/test_category_owner_unique.py

Unicité des catégories SCOPÉE par owner (issue #137, loop 2).

Règle métier : les catégories perso sont 100% par-user.
    - Système (owner NULL) : slug/name uniques GLOBALEMENT (un seul "inconnu").
    - Perso   (owner set)  : slug/name uniques PAR USER → deux users peuvent
      chacun avoir une catégorie "Restaurants" sans collision.

Couvre les UniqueConstraint partielles de transactions.models (migration 0018).
"""

import pytest
from django.db import IntegrityError, transaction

from transactions.models import Category, SubCategory


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="ua137@budget.ch", password="x")


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="ub137@budget.ch", password="x")


# =============================================================================
# Category — perso par user
# =============================================================================


@pytest.mark.django_db
def test_two_users_can_each_create_same_named_category(user_a, user_b):
    """Acceptance #137 : deux users créent chacun une perso 'Restaurants'."""
    ca = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_a, is_system=False
    )
    cb = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_b, is_system=False
    )
    assert ca.pk != cb.pk
    assert ca.owner_id == user_a.pk
    assert cb.owner_id == user_b.pk
    # Même slug, même nom, deux lignes distinctes : c'est le comportement attendu.
    assert ca.slug == cb.slug == "restaurants"


@pytest.mark.django_db
def test_for_user_isolates_perso_categories(user_a, user_b):
    """Un user ne voit jamais la perso d'un autre via .for_user()."""
    ca = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_a, is_system=False
    )
    cb = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_b, is_system=False
    )
    visible_a = set(Category.objects.for_user(user_a).values_list("pk", flat=True))
    visible_b = set(Category.objects.for_user(user_b).values_list("pk", flat=True))
    assert ca.pk in visible_a and cb.pk not in visible_a
    assert cb.pk in visible_b and ca.pk not in visible_b


@pytest.mark.django_db
def test_same_user_cannot_duplicate_slug(user_a):
    Category.objects.create(name="Resto 1", slug="resto", owner=user_a, is_system=False)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Category.objects.create(
                name="Resto 2", slug="resto", owner=user_a, is_system=False
            )


@pytest.mark.django_db
def test_same_user_cannot_duplicate_name(user_a):
    Category.objects.create(
        name="Restaurants", slug="resto-a", owner=user_a, is_system=False
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Category.objects.create(
                name="Restaurants", slug="resto-b", owner=user_a, is_system=False
            )


@pytest.mark.django_db
def test_system_slug_stays_globally_unique(db):
    Category.objects.create(name="SysUniq", slug="sys-uniq", owner=None, is_system=True)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Category.objects.create(
                name="SysUniq bis", slug="sys-uniq", owner=None, is_system=True
            )


@pytest.mark.django_db
def test_system_name_stays_globally_unique(db):
    Category.objects.create(
        name="Système X", slug="systeme-x-a", owner=None, is_system=True
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Category.objects.create(
                name="Système X", slug="systeme-x-b", owner=None, is_system=True
            )


# =============================================================================
# SubCategory — perso par user
# =============================================================================


@pytest.mark.django_db
def test_two_users_can_each_create_same_named_subcategory(user_a, user_b):
    """Sous-cat perso : 'Pizza' sous le 'Restaurants' de chaque user."""
    ca = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_a, is_system=False
    )
    cb = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_b, is_system=False
    )
    sa = SubCategory.objects.create(
        category=ca, name="Pizza", slug="pizza", owner=user_a, is_system=False
    )
    sb = SubCategory.objects.create(
        category=cb, name="Pizza", slug="pizza", owner=user_b, is_system=False
    )
    assert sa.pk != sb.pk
    assert sa.slug == sb.slug == "pizza"


@pytest.mark.django_db
def test_same_user_cannot_duplicate_subcategory_slug(user_a):
    cat = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_a, is_system=False
    )
    SubCategory.objects.create(
        category=cat, name="Pizza", slug="pizza", owner=user_a, is_system=False
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubCategory.objects.create(
                category=cat,
                name="Pizza autre",
                slug="pizza",
                owner=user_a,
                is_system=False,
            )


@pytest.mark.django_db
def test_subcategory_name_unique_within_same_category(user_a):
    """(category, name) reste unique — deux 'Pizza' dans le même parent → refus."""
    cat = Category.objects.create(
        name="Restaurants", slug="restaurants", owner=user_a, is_system=False
    )
    SubCategory.objects.create(
        category=cat, name="Pizza", slug="pizza-1", owner=user_a, is_system=False
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubCategory.objects.create(
                category=cat,
                name="Pizza",
                slug="pizza-2",
                owner=user_a,
                is_system=False,
            )


@pytest.mark.django_db
def test_system_subcategory_slug_stays_globally_unique(db):
    cat = Category.objects.create(
        name="Système", slug="systeme", owner=None, is_system=True
    )
    SubCategory.objects.create(
        category=cat, name="Sub", slug="sub-sys", owner=None, is_system=True
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubCategory.objects.create(
                category=cat,
                name="Sub bis",
                slug="sub-sys",
                owner=None,
                is_system=True,
            )

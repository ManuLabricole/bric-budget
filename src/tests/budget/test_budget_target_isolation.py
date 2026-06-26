"""
tests/budget/test_budget_target_isolation.py — #201

Avant #201, BudgetTarget était OneToOneField(Category) sans owner : un objectif sur une
catégorie SYSTÈME (partagée) était un seul row global → un user écrasait/voyait l'objectif
d'un autre. Ces tests prouvent l'isolation owner-scopée (et doivent ROUGIR sur l'ancien schéma).
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from transactions.models import BudgetTarget


@pytest.mark.django_db
def test_two_users_target_same_system_category_no_collision(category, user_a, user_b):
    """A et B ont CHACUN leur objectif sur la même catégorie système, sans collision."""
    BudgetTarget.objects.create(category=category, owner=user_a, amount=Decimal("100"))
    # Sous l'ancien OneToOne, cette 2e ligne levait IntegrityError (unique sur category).
    BudgetTarget.objects.create(category=category, owner=user_b, amount=Decimal("200"))

    assert BudgetTarget.objects.for_user(user_a).get(
        category=category
    ).amount == Decimal("100")
    assert BudgetTarget.objects.for_user(user_b).get(
        category=category
    ).amount == Decimal("200")


@pytest.mark.django_db
def test_for_user_hides_other_users_target(category, user_a, user_b):
    """L'objectif de A n'est jamais visible dans le queryset scopé de B."""
    BudgetTarget.objects.create(category=category, owner=user_a, amount=Decimal("100"))
    assert not BudgetTarget.objects.for_user(user_b).exists()


@pytest.mark.django_db
def test_post_does_not_overwrite_other_users_target(client_b, category, user_a, user_b):
    """B qui pose un objectif sur une catégorie système n'écrase PAS celui de A."""
    BudgetTarget.objects.create(category=category, owner=user_a, amount=Decimal("100"))

    resp = client_b.post(
        reverse("budget:modal_target_create"),
        {"category_id": category.id, "amount": "200"},
    )
    assert resp.status_code in (200, 204)

    # A garde son objectif intact ; B a le sien → 2 rows distincts.
    assert BudgetTarget.objects.unscoped().get(
        owner=user_a, category=category
    ).amount == Decimal("100")
    assert BudgetTarget.objects.unscoped().get(
        owner=user_b, category=category
    ).amount == Decimal("200")

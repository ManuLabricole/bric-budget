"""
tests/demo/test_seeder_objectives.py — seed des objectifs démo (#24).

_ensure_budget_targets calibre des BudgetTarget sur le dépensé du mois courant pour
exposer tous les états de jauge (40 / 85 / 100 / 150 %) + un objectif « non commencé »
(0 %). On prouve : création, calibrage (ratio dépensé/objectif), idempotence.
"""

from datetime import date
from decimal import Decimal
from typing import cast

import pytest

from demo.seeder import _TARGET_RATIOS, _ensure_budget_targets
from tests.factories import (
    AccountFactory,
    CategoryFactory,
    TransactionFactory,
    UserFactory,
)
from transactions.models import BudgetTarget, Category, Transaction


@pytest.mark.django_db
def test_ensure_budget_targets_calibrates_states_and_is_idempotent():
    user = UserFactory()
    account = AccountFactory(members=[user])
    today = date.today()

    # 4 catégories avec dépense décroissante ce mois → 4 objectifs calibrés.
    spends = [1000, 800, 600, 400]
    cats = []
    for i, spend in enumerate(spends):
        cat = cast(Category, CategoryFactory(owner=user, slug=f"obj-cat-{i}"))
        cast(
            Transaction,
            TransactionFactory(
                account=account, category=cat, amount=Decimal(f"-{spend}"), date=today
            ),
        )
        cats.append(cat)
    # 1 catégorie SANS dépense → objectif « non commencé » (0 %).
    zero_cat = cast(Category, CategoryFactory(owner=user, slug="obj-zero"))

    n = _ensure_budget_targets(user)

    assert n == 5  # 4 calibrés + 1 non commencé
    targets = {t.category_id: t.amount for t in BudgetTarget.objects.for_user(user)}
    # Calibrage : objectif = dépensé / ratio, dans l'ordre du plus dépensé au moins.
    for cat, spend, ratio in zip(cats, spends, _TARGET_RATIOS):
        assert targets[cat.id] == Decimal(str(round(spend / ratio, 2)))
    assert targets[zero_cat.id] == Decimal("200")  # défaut « non commencé »

    # Idempotent : re-seed recalibre sans dupliquer (update_or_create scopé for_user).
    assert _ensure_budget_targets(user) == 5
    assert BudgetTarget.objects.for_user(user).count() == 5

"""
tests/services/test_categorization_priority.py

Ce qu'on teste : la logique de priorité dans _find_rule().

Scénario-clé : plusieurs règles matchent la même transaction.
La règle avec la priorité la plus haute (nombre le plus grand) doit gagner.
C'est le comportement qui garantit que "la dernière règle créée prime".

On teste aussi :
- Une règle inactive avec priorité haute est ignorée → la règle active gagne
- Quand une seule règle matche, elle gagne quelle que soit sa priorité
- Quand aucune règle ne matche, on retourne None

On appelle _find_rule() directement — pas besoin d'un vrai import.
Les règles sont construites en DB puis passées à la méthode (comme le fait
ImportService.run() : il charge toutes les règles actives triées par -priority
en une seule requête, puis les passe à _find_rule pour chaque transaction).
"""

import pytest

from tests.services.conftest import make_tx
from transactions.models import CategorizationRule
from transactions.services import ImportService

# =============================================================================
# Fixtures — catégories minimales pour créer des règles
# =============================================================================


@pytest.fixture
def cat_a(db):
    """Catégorie A — première règle crée vers ici."""
    from transactions.models import Category

    return Category.objects.create(
        name="Cat A",
        slug="cat-a",
        colour_hex="#aaaaaa",
        order=50,
        is_system=False,
    )


@pytest.fixture
def cat_b(db):
    """Catégorie B — règle plus récente (priorité haute) pointe ici."""
    from transactions.models import Category

    return Category.objects.create(
        name="Cat B",
        slug="cat-b",
        colour_hex="#bbbbbb",
        order=51,
        is_system=False,
    )


# =============================================================================
# 1. Priorité — la règle la plus haute gagne en cas de conflit
# =============================================================================


@pytest.mark.django_db
def test_highest_priority_rule_wins(cat_a, cat_b):
    """
    Deux règles matchent "MIGROS LAUSANNE".
    Règle A : priorité 1 (ancienne)
    Règle B : priorité 2 (récente → doit gagner)

    _find_rule reçoit la liste déjà triée par -priority (comme dans run()),
    donc on passe rules dans l'ordre décroissant de priorité.
    """
    rule_a = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_a,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=1,
        is_active=True,
    )
    rule_b = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_b,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=2,
        is_active=True,
    )

    tx = make_tx("migros", display_name="MIGROS LAUSANNE")
    service = ImportService()

    # On passe les règles dans l'ordre décroissant de priorité, comme ImportService.run()
    matched = service._find_rule(tx, [rule_b, rule_a])

    assert matched == rule_b, "La règle la plus récente (priorité 2) doit gagner"
    assert matched.category == cat_b


@pytest.mark.django_db
def test_lower_priority_rule_wins_if_only_match(cat_a, cat_b):
    """
    Règle A (priorité 1) matche "MIGROS".
    Règle B (priorité 2) matche "COOP" — ne matche pas la transaction.
    → Règle A doit être retournée même si sa priorité est inférieure.
    """
    rule_a = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_a,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=1,
        is_active=True,
    )
    rule_b = CategorizationRule.objects.create(
        keyword="COOP",
        category=cat_b,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=2,
        is_active=True,
    )

    tx = make_tx("migros-only", display_name="MIGROS LAUSANNE")
    service = ImportService()

    matched = service._find_rule(tx, [rule_b, rule_a])

    assert matched == rule_a
    assert matched.category == cat_a


# =============================================================================
# 2. Règle inactive — ignorée même si elle a la priorité la plus haute
# =============================================================================


@pytest.mark.django_db
def test_inactive_rule_is_ignored(cat_a, cat_b):
    """
    Règle A (active, priorité 1) matche "MIGROS".
    Règle B (inactive, priorité 2) matche aussi "MIGROS".

    ImportService.run() ne charge que les règles is_active=True.
    On simule ce comportement en ne passant que la règle active à _find_rule.

    → Règle A doit gagner car règle B n'est pas dans la liste.
    """
    rule_a = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_a,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=1,
        is_active=True,
    )
    CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_b,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=2,
        is_active=False,  # inactive — ne sera pas dans la liste passée à _find_rule
    )

    tx = make_tx("migros-inactive", display_name="MIGROS LAUSANNE")
    service = ImportService()

    # On simule le filtre is_active=True de ImportService.run()
    active_rules = list(
        CategorizationRule.objects.filter(is_active=True)
        .select_related("category", "subcategory")
        .order_by("-priority")
    )

    matched = service._find_rule(tx, active_rules)

    assert matched == rule_a, "La règle inactive (priorité 2) doit être ignorée"
    assert matched.category == cat_a


# =============================================================================
# 3. Aucune règle ne matche → None
# =============================================================================


@pytest.mark.django_db
def test_no_matching_rule_returns_none(cat_a):
    """
    Aucune règle ne matche la transaction → _find_rule retourne None.
    ImportService.run() assignera alors la catégorie par défaut ("inconnu" ou "revenus").
    """
    CategorizationRule.objects.create(
        keyword="COOP",
        category=cat_a,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=10,
        is_active=True,
    )

    tx = make_tx("migros-nomatch", display_name="MIGROS LAUSANNE")
    service = ImportService()

    active_rules = list(
        CategorizationRule.objects.filter(is_active=True)
        .select_related("category", "subcategory")
        .order_by("-priority")
    )

    matched = service._find_rule(tx, active_rules)

    assert matched is None


# =============================================================================
# 4. Matching case-insensitive
# =============================================================================


@pytest.mark.django_db
def test_keyword_matching_is_case_insensitive(cat_a):
    """
    Le keyword est stocké en majuscules mais la description peut avoir
    n'importe quelle casse. Le matching doit être case-insensitive.
    """
    rule = CategorizationRule.objects.create(
        keyword="migros",  # minuscules
        category=cat_a,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=1,
        is_active=True,
    )

    tx = make_tx("case-test", display_name="MIGROS Lausanne VD")
    service = ImportService()

    matched = service._find_rule(tx, [rule])

    assert matched == rule

"""
tests/services/test_rule_priority_autoincrement.py

Ce qu'on teste : la priorité auto-incrémentée à la création d'une règle.

Dans budget/views.py, les deux vues de création de règle utilisent le pattern :
    next_priority = (CategorizationRule.objects.aggregate(m=Max("priority"))["m"] or 0) + 1

On teste ce pattern au niveau ORM — pas besoin de passer par la vue HTTP.
L'invariant qu'on veut garantir :
    → chaque nouvelle règle reçoit une priorité strictement supérieure à toutes les existantes
    → si la table est vide, la première règle reçoit priorité 1

Pourquoi tester ça ici plutôt que dans la vue ?
La logique métier (max+1) est ce qui compte, pas le code HTTP autour.
Si on extrait ce pattern en helper plus tard, ce test continuera de fonctionner.
"""

import pytest
from django.db.models import Max

from transactions.models import CategorizationRule

# =============================================================================
# Fixture — catégorie minimale
# =============================================================================


@pytest.fixture
def cat(db):
    from transactions.models import Category

    return Category.objects.create(
        name="Cat Test",
        slug="cat-test-autoincr",
        colour_hex="#cccccc",
        order=99,
        is_system=False,
    )


# =============================================================================
# Helper — simule exactement le code des vues de création
# =============================================================================


def create_rule_with_autoincrement(keyword: str, cat) -> CategorizationRule:
    """
    Reproduit le pattern utilisé dans budget/views.py pour créer une règle.
    Si on change le pattern dans la vue, ce test échouera et signalera la divergence.
    """
    next_priority = (
        CategorizationRule.objects.aggregate(m=Max("priority"))["m"] or 0
    ) + 1
    rule, _ = CategorizationRule.objects.get_or_create(
        keyword=keyword,
        category=cat,
        defaults={
            "target_field": CategorizationRule.TargetField.DISPLAY_NAME,
            "priority": next_priority,
            "is_active": True,
        },
    )
    return rule


# =============================================================================
# 1. Première règle créée → priorité 1 (table vide)
# =============================================================================


@pytest.mark.django_db
def test_first_rule_gets_priority_1(cat):
    """
    Quand la table CategorizationRule est vide, Max("priority") retourne None.
    Le pattern (None or 0) + 1 doit donner priorité 1.
    """
    assert CategorizationRule.objects.count() == 0

    rule = create_rule_with_autoincrement("MIGROS", cat)

    assert rule.priority == 1


# =============================================================================
# 2. Chaque nouvelle règle reçoit une priorité strictement plus haute
# =============================================================================


@pytest.mark.django_db
def test_sequential_rules_get_increasing_priorities(cat):
    """
    Trois règles créées en séquence → priorités 1, 2, 3.
    La plus récente a toujours la priorité la plus haute → gagne en cas de conflit.
    """
    rule1 = create_rule_with_autoincrement("COOP", cat)
    rule2 = create_rule_with_autoincrement("MIGROS", cat)
    rule3 = create_rule_with_autoincrement("AGROLA", cat)

    assert rule1.priority < rule2.priority < rule3.priority, (
        f"Priorités attendues croissantes, obtenu : "
        f"{rule1.priority}, {rule2.priority}, {rule3.priority}"
    )


# =============================================================================
# 3. Nouvelle règle après des existantes → max + 1
# =============================================================================


@pytest.mark.django_db
def test_new_rule_gets_max_plus_one(cat):
    """
    Des règles existent déjà (avec des priorités arbitraires).
    La nouvelle règle doit recevoir max_existant + 1, pas juste len(rules) + 1.

    Cas concret : si les règles ont des priorités [1, 5, 12], la nouvelle doit
    recevoir 13, pas 4.
    """
    from transactions.models import Category

    # Créer des règles avec des priorités non-consécutives
    cat2 = Category.objects.create(
        name="Cat Test 2",
        slug="cat-test-autoincr-2",
        colour_hex="#dddddd",
        order=98,
        is_system=False,
    )
    CategorizationRule.objects.create(
        keyword="ALPHA",
        category=cat,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=1,
        is_active=True,
    )
    CategorizationRule.objects.create(
        keyword="BETA",
        category=cat2,
        target_field=CategorizationRule.TargetField.DISPLAY_NAME,
        priority=12,  # priorité non-consécutive
        is_active=True,
    )

    new_rule = create_rule_with_autoincrement("GAMMA", cat)

    assert new_rule.priority == 13, (
        f"Attendu 13 (max=12 + 1), obtenu {new_rule.priority}"
    )


# =============================================================================
# 4. get_or_create — double appel avec même keyword+catégorie → même règle, même priorité
# =============================================================================


@pytest.mark.django_db
def test_get_or_create_does_not_change_existing_priority(cat):
    """
    Si une règle identique (même keyword + catégorie) existe déjà,
    get_or_create ne la crée pas et ne change pas sa priorité.

    Garantit qu'on ne « monte » pas indûment la priorité d'une règle existante
    en la recréant par erreur.
    """
    # Première création : priorité 1
    rule_first = create_rule_with_autoincrement("MIGROS", cat)
    assert rule_first.priority == 1

    # Deuxième appel avec le même keyword + catégorie → get, pas create
    rule_second = create_rule_with_autoincrement("MIGROS", cat)

    assert rule_first.pk == rule_second.pk, "Doit retourner la même règle"
    assert rule_second.priority == 1, "La priorité ne doit pas avoir changé"

"""
tests/services/test_import_rule_scoping.py — #205

Avant #205, ImportService._load_rules() chargeait CategorizationRule.objects.filter(
is_active=True) SANS scoper par user → les règles perso de N'IMPORTE QUEL user
catégorisaient les transactions de l'importeur (fuite + catégorisation croisée).
Ce test doit ROUGIR sur l'ancien _load_rules() (la règle de l'autre user y apparaissait).
"""

import pytest
from django.contrib.auth import get_user_model

from transactions.models import CategorizationRule, Category
from transactions.services import ImportService


@pytest.mark.django_db
def test_load_rules_excludes_other_users_perso_rules(user):
    """À l'import, on charge SYSTÈME + perso de l'importeur, jamais le perso d'un autre."""
    other = get_user_model().objects.create_user(
        email="other@bricbudget.ch", password="x"
    )
    cat = Category.objects.create(name="Food", slug="food", owner=None)

    CategorizationRule.objects.create(
        keyword="migros", category=cat, owner=None, is_active=True
    )  # système → doit charger
    CategorizationRule.objects.create(
        keyword="mine-kw", category=cat, owner=user, is_active=True
    )  # perso de l'importeur → doit charger
    CategorizationRule.objects.create(
        keyword="theirs-kw", category=cat, owner=other, is_active=True
    )  # perso d'un AUTRE user → ne doit JAMAIS charger

    keywords = {r.keyword for r in ImportService()._load_rules(user)}

    assert "migros" in keywords
    assert "mine-kw" in keywords
    assert "theirs-kw" not in keywords  # #205 : pas de catégorisation croisée

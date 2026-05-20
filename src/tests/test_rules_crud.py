"""
tests/test_rules_crud.py

Tests : CRUD règles de catégorisation (Phase 2G)

Vues couvertes :
    - budget_panel_rules_list        (GET  /budget/panel/rules/)
    - budget_rule_toggle_active      (POST /budget/rules/<id>/toggle/)
    - budget_rule_delete             (POST /budget/rules/<id>/delete/)
    - budget_rule_row_edit           (GET  /budget/rules/<id>/edit/)
    - budget_rule_edit_submit        (POST /budget/rules/<id>/edit/submit/)

Note architecture (Phase 3) :
    CategorizationRule n'a pas de ForeignKey user → les règles sont partagées entre
    tous les utilisateurs connectés. En Phase 3 multi-user, un champ `owner` ou un
    filtre `account` sera nécessaire. Ces tests ne vérifient donc PAS d'IDOR, mais
    notent le risque en commentaire.
"""

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import CategorizationRule, Category

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="rules@test.ch", password="pass")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.login(email="rules@test.ch", password="pass")
    return c


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Alimentation RULES",
        slug="alimentation-rules-crud",
        colour_hex="#aaa",
        order=50,
        is_system=False,
    )


@pytest.fixture
def cat2(db):
    """Deuxième catégorie pour tester le changement de catégorie."""
    return Category.objects.create(
        name="Transport RULES",
        slug="transport-rules-crud",
        colour_hex="#bbb",
        order=51,
        is_system=False,
    )


@pytest.fixture
def rule(db, cat):
    return CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat,
        target_field="display_name",
        priority=1,
        is_active=True,
    )


@pytest.fixture
def inactive_rule(db, cat):
    return CategorizationRule.objects.create(
        keyword="COOP",
        category=cat,
        target_field="display_name",
        priority=2,
        is_active=False,
    )


# =============================================================================
# budget_panel_rules_list — GET
# =============================================================================


@pytest.mark.django_db
def test_panel_rules_list_returns_200(auth_client, rule):
    response = auth_client.get(reverse("budget:panel_rules_list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_panel_rules_list_shows_rule_keyword(auth_client, rule):
    """La liste affiche le keyword de la règle."""
    response = auth_client.get(reverse("budget:panel_rules_list"))
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_panel_rules_list_is_partial_html(auth_client, rule):
    """La liste est un fragment HTMX, pas une page complète."""
    response = auth_client.get(reverse("budget:panel_rules_list"))
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content


# =============================================================================
# budget_rule_toggle_active — POST
# =============================================================================


@pytest.mark.django_db
def test_rule_toggle_active_sets_is_active_false(auth_client, rule):
    """Règle active → toggle → is_active=False en DB."""
    assert rule.is_active is True
    auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    rule.refresh_from_db()
    assert rule.is_active is False


@pytest.mark.django_db
def test_rule_toggle_active_sets_is_active_true(auth_client, inactive_rule):
    """Règle inactive → toggle → is_active=True en DB."""
    assert inactive_rule.is_active is False
    auth_client.post(reverse("budget:rule_toggle_active", args=[inactive_rule.id]))
    inactive_rule.refresh_from_db()
    assert inactive_rule.is_active is True


@pytest.mark.django_db
def test_rule_toggle_active_double_flip_restores_state(auth_client, rule):
    """Deux toggles successifs → état initial restauré."""
    for _ in range(2):
        auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    rule.refresh_from_db()
    assert rule.is_active is True


@pytest.mark.django_db
def test_rule_toggle_active_returns_200(auth_client, rule):
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_rule_toggle_active_returns_partial_html(auth_client, rule):
    """La réponse est un fragment (ligne de règle), pas une page complète."""
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_rule_toggle_active_response_contains_keyword(auth_client, rule):
    """Le fragment retourné contient le keyword de la règle."""
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_rule_toggle_active_404_for_nonexistent_rule(auth_client):
    """ID inconnu → 404."""
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[999999]))
    assert response.status_code == 404


# =============================================================================
# budget_rule_delete — POST
# =============================================================================


@pytest.mark.django_db
def test_rule_delete_removes_from_db(auth_client, rule):
    """DELETE → la règle n'existe plus en DB."""
    rule_id = rule.id
    auth_client.post(reverse("budget:rule_delete", args=[rule.id]))
    assert not CategorizationRule.objects.filter(id=rule_id).exists()


@pytest.mark.django_db
def test_rule_delete_returns_200(auth_client, rule):
    response = auth_client.post(reverse("budget:rule_delete", args=[rule.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_rule_delete_returns_empty_body(auth_client, rule):
    """Réponse vide → HTMX retire la ligne du DOM via hx-swap='outerHTML'."""
    response = auth_client.post(reverse("budget:rule_delete", args=[rule.id]))
    assert response.content == b""


@pytest.mark.django_db
def test_rule_delete_404_for_nonexistent_rule(auth_client):
    """ID inconnu → 404."""
    response = auth_client.post(reverse("budget:rule_delete", args=[999999]))
    assert response.status_code == 404


# =============================================================================
# budget_rule_row_edit — GET
# =============================================================================


@pytest.mark.django_db
def test_rule_row_edit_returns_200(auth_client, rule):
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_rule_row_edit_shows_keyword_in_form(auth_client, rule):
    """Le formulaire pré-remplit le keyword de la règle."""
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule.id]))
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_rule_row_edit_is_partial_html(auth_client, rule):
    """Le formulaire est un fragment, pas une page complète."""
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule.id]))
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_rule_row_edit_cancel_returns_read_row(auth_client, rule):
    """?cancel=1 → retourne la ligne en mode lecture (pas le formulaire d'édition)."""
    response = auth_client.get(
        reverse("budget:rule_row_edit", args=[rule.id]), {"cancel": "1"}
    )
    assert response.status_code == 200
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_rule_row_edit_404_for_nonexistent_rule(auth_client):
    response = auth_client.get(reverse("budget:rule_row_edit", args=[999999]))
    assert response.status_code == 404


# =============================================================================
# budget_rule_edit_submit — POST
# =============================================================================


@pytest.mark.django_db
def test_rule_edit_submit_updates_keyword(auth_client, rule, cat):
    """Nouveau keyword → sauvegardé en DB."""
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "coop", "category_id": cat.id},
    )
    rule.refresh_from_db()
    assert rule.keyword == "COOP"


@pytest.mark.django_db
def test_rule_edit_submit_normalizes_keyword_to_uppercase(auth_client, rule, cat):
    """Le keyword est normalisé en UPPERCASE avant sauvegarde."""
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "   sncf   ", "category_id": cat.id},
    )
    rule.refresh_from_db()
    assert rule.keyword == "SNCF"


@pytest.mark.django_db
def test_rule_edit_submit_updates_category(auth_client, rule, cat2):
    """Changement de catégorie → sauvegardé en DB."""
    original_cat_id = rule.category_id
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": rule.keyword, "category_id": cat2.id},
    )
    rule.refresh_from_db()
    assert rule.category_id == cat2.id
    assert rule.category_id != original_cat_id


@pytest.mark.django_db
def test_rule_edit_submit_missing_keyword_leaves_rule_unchanged(auth_client, rule, cat):
    """Si keyword absent du POST → règle inchangée (validation silencieuse)."""
    original_keyword = rule.keyword
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"category_id": cat.id},  # keyword manquant
    )
    rule.refresh_from_db()
    assert rule.keyword == original_keyword


@pytest.mark.django_db
def test_rule_edit_submit_missing_category_leaves_rule_unchanged(auth_client, rule):
    """Si category_id absent du POST → règle inchangée."""
    original_cat_id = rule.category_id
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "NEWKW"},  # category_id manquant
    )
    rule.refresh_from_db()
    assert rule.category_id == original_cat_id


@pytest.mark.django_db
def test_rule_edit_submit_returns_200(auth_client, rule, cat):
    response = auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "COOP", "category_id": cat.id},
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_rule_edit_submit_returns_partial_html(auth_client, rule, cat):
    """La réponse est un fragment (ligne lue avec nouvelles valeurs)."""
    response = auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "COOP", "category_id": cat.id},
    )
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_rule_edit_submit_404_for_nonexistent_rule(auth_client, cat):
    response = auth_client.post(
        reverse("budget:rule_edit_submit", args=[999999]),
        {"keyword": "TEST", "category_id": cat.id},
    )
    assert response.status_code == 404

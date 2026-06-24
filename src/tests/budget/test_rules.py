"""
tests/budget/test_rules.py

Tests des vues de gestion des règles de catégorisation :
  - panel_rules_list, rule_toggle_active, rule_delete, rule_row_edit, rule_edit_submit
  - export JSON des règles (budget_export_rules_download)
"""

import json

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

    return get_user_model().objects.create_user(
        email="rules@budget.ch", password="pass"
    )


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Rules Test Cat",
        slug="rules-test-cat",
        colour_hex="#aaa",
        order=50,
        is_system=False,
    )


@pytest.fixture
def cat2(db):
    return Category.objects.create(
        name="Rules Test Cat2",
        slug="rules-test-cat2",
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


@pytest.fixture
def rules(db, cat):
    """Une règle active + une règle inactive pour les tests d'export."""
    active = CategorizationRule.objects.create(
        keyword="MIGROS-EXPORT",
        category=cat,
        target_field="description_raw",
        priority=10,
        is_active=True,
    )
    inactive = CategorizationRule.objects.create(
        keyword="COOP-EXPORT",
        category=cat,
        target_field="description_raw",
        priority=11,
        is_active=False,
    )
    return active, inactive


# =============================================================================
# panel_rules_list — GET
# =============================================================================


@pytest.mark.django_db
def test_panel_rules_list_returns_200(auth_client, rule):
    response = auth_client.get(reverse("budget:panel_rules_list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_panel_rules_list_shows_rule_keyword(auth_client, rule):
    response = auth_client.get(reverse("budget:panel_rules_list"))
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_panel_rules_list_is_partial_html(auth_client, rule):
    response = auth_client.get(reverse("budget:panel_rules_list"))
    assert "<!DOCTYPE html>" not in response.content.decode()


# =============================================================================
# rule_toggle_active — POST
# =============================================================================


@pytest.mark.django_db
def test_rule_toggle_active_sets_is_active_false(auth_client, rule):
    auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    rule.refresh_from_db()
    assert rule.is_active is False


@pytest.mark.django_db
def test_rule_toggle_active_sets_is_active_true(auth_client, inactive_rule):
    auth_client.post(reverse("budget:rule_toggle_active", args=[inactive_rule.id]))
    inactive_rule.refresh_from_db()
    assert inactive_rule.is_active is True


@pytest.mark.django_db
def test_rule_toggle_active_double_flip_restores_state(auth_client, rule):
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
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_rule_toggle_active_response_contains_keyword(auth_client, rule):
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[rule.id]))
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_rule_toggle_active_404_for_nonexistent_rule(auth_client):
    response = auth_client.post(reverse("budget:rule_toggle_active", args=[999999]))
    assert response.status_code == 404


# =============================================================================
# rule_delete — POST
# =============================================================================


@pytest.mark.django_db
def test_rule_delete_removes_from_db(auth_client, rule):
    rule_id = rule.id
    auth_client.post(reverse("budget:rule_delete", args=[rule.id]))
    assert not CategorizationRule.objects.unscoped().filter(id=rule_id).exists()


@pytest.mark.django_db
def test_rule_delete_returns_200(auth_client, rule):
    response = auth_client.post(reverse("budget:rule_delete", args=[rule.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_rule_delete_returns_empty_body(auth_client, rule):
    response = auth_client.post(reverse("budget:rule_delete", args=[rule.id]))
    assert response.content == b""


@pytest.mark.django_db
def test_rule_delete_404_for_nonexistent_rule(auth_client):
    response = auth_client.post(reverse("budget:rule_delete", args=[999999]))
    assert response.status_code == 404


# =============================================================================
# rule_row_edit — GET
# =============================================================================


@pytest.mark.django_db
def test_rule_row_edit_returns_200(auth_client, rule):
    assert (
        auth_client.get(reverse("budget:rule_row_edit", args=[rule.id])).status_code
        == 200
    )


@pytest.mark.django_db
def test_rule_row_edit_shows_keyword_in_form(auth_client, rule):
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule.id]))
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_rule_row_edit_is_partial_html(auth_client, rule):
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule.id]))
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_rule_row_edit_cancel_returns_read_row(auth_client, rule):
    response = auth_client.get(
        reverse("budget:rule_row_edit", args=[rule.id]), {"cancel": "1"}
    )
    assert response.status_code == 200
    assert "MIGROS" in response.content.decode()


@pytest.mark.django_db
def test_rule_row_edit_404_for_nonexistent_rule(auth_client):
    assert (
        auth_client.get(reverse("budget:rule_row_edit", args=[999999])).status_code
        == 404
    )


# =============================================================================
# rule_edit_submit — POST
# =============================================================================


@pytest.mark.django_db
def test_rule_edit_submit_updates_keyword(auth_client, rule, cat):
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "coop", "category_id": cat.id},
    )
    rule.refresh_from_db()
    assert rule.keyword == "COOP"


@pytest.mark.django_db
def test_rule_edit_submit_normalizes_keyword_to_uppercase(auth_client, rule, cat):
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "   sncf   ", "category_id": cat.id},
    )
    rule.refresh_from_db()
    assert rule.keyword == "SNCF"


@pytest.mark.django_db
def test_rule_edit_submit_updates_category(auth_client, rule, cat2):
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
    original_keyword = rule.keyword
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"category_id": cat.id},
    )
    rule.refresh_from_db()
    assert rule.keyword == original_keyword


@pytest.mark.django_db
def test_rule_edit_submit_missing_category_leaves_rule_unchanged(auth_client, rule):
    original_cat_id = rule.category_id
    auth_client.post(
        reverse("budget:rule_edit_submit", args=[rule.id]),
        {"keyword": "NEWKW"},
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


# =============================================================================
# export_rules_download — GET
# =============================================================================


@pytest.mark.django_db
def test_export_requires_login():
    c = Client()
    r = c.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    assert r.status_code == 302
    assert "/login/" in r["Location"] or "/accounts/" in r["Location"]


@pytest.mark.django_db
def test_export_returns_json_attachment(auth_client, rules):
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    assert r.status_code == 200
    assert "application/json" in r["Content-Type"]
    assert "attachment" in r["Content-Disposition"]
    assert ".json" in r["Content-Disposition"]


@pytest.mark.django_db
def test_export_json_structure(auth_client, rules):
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    assert "exported_at" in data
    assert "count" in data
    assert "rules" in data
    assert isinstance(data["rules"], list)


@pytest.mark.django_db
def test_export_includes_all_rules(auth_client, rules):
    active, inactive = rules
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    keywords = [rule["keyword"] for rule in data["rules"]]
    assert active.keyword in keywords
    assert inactive.keyword in keywords
    assert data["count"] == len(data["rules"])


@pytest.mark.django_db
def test_export_preserves_is_active(auth_client, rules):
    active, inactive = rules
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    by_keyword = {rule["keyword"]: rule for rule in data["rules"]}
    assert by_keyword[active.keyword]["is_active"] is True
    assert by_keyword[inactive.keyword]["is_active"] is False


@pytest.mark.django_db
def test_export_rule_fields(auth_client, rules, cat):
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    rule = next(r for r in data["rules"] if r["keyword"] == "MIGROS-EXPORT")
    assert rule["keyword"] == "MIGROS-EXPORT"
    assert rule["category_slug"] == cat.slug
    assert rule["subcategory_slug"] is None
    assert rule["target_field"] == "description_raw"
    assert rule["is_active"] is True

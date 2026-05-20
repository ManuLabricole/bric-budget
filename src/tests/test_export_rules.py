"""
tests/test_export_rules.py

Tests : export règles de catégorisation en JSON (GET /budget/export/rules/)

Cas couverts :
    - réponse 200 + Content-Disposition attachment
    - format JSON valide avec les champs attendus
    - toutes les règles exportées (actives ET inactives)
    - is_active conservé fidèlement pour chaque règle
    - utilisateur non connecté → redirect 302
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

    return get_user_model().objects.create_user(email="export@test.ch", password="pass")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.login(email="export@test.ch", password="pass")
    return c


@pytest.fixture
def cat(db):
    return Category.objects.create(
        name="Alimentation EXPORT",
        slug="alimentation-export",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


@pytest.fixture
def rules(db, cat):
    """Une règle active + une règle inactive."""
    active = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat,
        target_field="description_raw",
        priority=1,
        is_active=True,
    )
    inactive = CategorizationRule.objects.create(
        keyword="COOP",
        category=cat,
        target_field="description_raw",
        priority=2,
        is_active=False,
    )
    return active, inactive


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.django_db
def test_export_requires_login():
    """Utilisateur non connecté → redirect vers login."""
    c = Client()
    r = c.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    assert r.status_code == 302
    assert "/login/" in r["Location"] or "/accounts/" in r["Location"]


@pytest.mark.django_db
def test_export_returns_json_attachment(auth_client, rules):
    """Réponse 200, Content-Type JSON, fichier attaché."""
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    assert r.status_code == 200
    assert "application/json" in r["Content-Type"]
    assert "attachment" in r["Content-Disposition"]
    assert ".json" in r["Content-Disposition"]


@pytest.mark.django_db
def test_export_json_structure(auth_client, rules):
    """Le JSON contient les clés exported_at, count, rules."""
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    assert "exported_at" in data
    assert "count" in data
    assert "rules" in data
    assert isinstance(data["rules"], list)


@pytest.mark.django_db
def test_export_includes_all_rules(auth_client, rules):
    """Toutes les règles sont exportées — actives ET inactives."""
    active, inactive = rules
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    keywords = [rule["keyword"] for rule in data["rules"]]
    assert active.keyword in keywords
    assert inactive.keyword in keywords
    assert data["count"] == len(data["rules"])


@pytest.mark.django_db
def test_export_preserves_is_active(auth_client, rules):
    """is_active est fidèlement exporté pour chaque règle."""
    active, inactive = rules
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    by_keyword = {rule["keyword"]: rule for rule in data["rules"]}
    assert by_keyword[active.keyword]["is_active"] is True
    assert by_keyword[inactive.keyword]["is_active"] is False


@pytest.mark.django_db
def test_export_rule_fields(auth_client, rules, cat):
    """Chaque règle contient tous les champs attendus."""
    r = auth_client.get(reverse("budget:export_rules_download"), HTTP_HOST="localhost")
    data = json.loads(r.content)
    rule = next(r for r in data["rules"] if r["keyword"] == "MIGROS")
    assert rule["keyword"] == "MIGROS"
    assert rule["category_slug"] == cat.slug
    assert rule["subcategory_slug"] is None
    assert rule["target_field"] == "description_raw"
    assert rule["priority"] == 1
    assert rule["is_active"] is True

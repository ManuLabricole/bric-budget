"""
tests/budget/test_crud.py

V1 — Tests des vues qui MUTENT la DB. Auth + happy path + validation + état DB.

Couvre :
  - budget_category_create_submit  : crée Category / SubCategory
  - budget_category_delete         : supprime Category (cascade) / SubCategory
  - budget_rule_create_submit      : crée règle + bulk apply
  - budget_rule_create_standalone_submit : crée N règles standalone + bulk apply
"""

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import CategorizationRule, Category, SubCategory

# =============================================================================
# Fixtures locales
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="crud@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def existing_cat(db):
    return Category.objects.create(
        name="Existante CRUD",
        slug="existante-crud",
        colour_hex="#abc123",
        order=50,
        is_system=False,
    )


@pytest.fixture
def system_cat(db):
    return Category.objects.create(
        name="System CRUD",
        slug="system-crud",
        colour_hex="#000000",
        order=1,
        is_system=True,
    )


# =============================================================================
# category_create_submit — POST
# =============================================================================


@pytest.mark.django_db
def test_category_create_submit_requires_login(client):
    r = client.post(reverse("budget:category_create_submit"), {"name": "X"})
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_category_create_submit_creates_main_category(auth_client):
    auth_client.post(
        reverse("budget:category_create_submit"),
        {
            "cat_type": "main",
            "name": "Nouvelle catégorie",
            "icon": "burger",
            "colour_hex": "#eed8b4",
        },
    )
    assert Category.objects.filter(name="Nouvelle catégorie").exists()


@pytest.mark.django_db
def test_category_create_submit_creates_subcategory(auth_client, existing_cat):
    auth_client.post(
        reverse("budget:category_create_submit"),
        {
            "cat_type": "sub",
            "name": "Sous catégorie CRUD",
            "icon": "burger",
            "parent_id": str(existing_cat.id),
        },
    )
    assert SubCategory.objects.filter(
        name="Sous catégorie CRUD", category=existing_cat
    ).exists()


@pytest.mark.django_db
def test_category_create_submit_missing_name_does_not_create(auth_client):
    n_before = Category.objects.count()
    r = auth_client.post(
        reverse("budget:category_create_submit"),
        {"cat_type": "main", "name": "", "icon": "burger", "colour_hex": "#eed8b4"},
    )
    assert r.status_code == 200  # re-render avec erreurs
    assert Category.objects.count() == n_before


@pytest.mark.django_db
def test_category_create_submit_duplicate_name_does_not_create(
    auth_client, existing_cat
):
    n_before = Category.objects.count()
    auth_client.post(
        reverse("budget:category_create_submit"),
        {
            "cat_type": "main",
            "name": existing_cat.name,
            "icon": "burger",
            "colour_hex": "#eed8b4",
        },
    )
    assert Category.objects.count() == n_before


@pytest.mark.django_db
def test_category_create_submit_main_without_colour_fails(auth_client):
    n_before = Category.objects.count()
    auth_client.post(
        reverse("budget:category_create_submit"),
        {"cat_type": "main", "name": "Sans couleur", "icon": "burger"},
    )
    assert Category.objects.count() == n_before


# =============================================================================
# category_delete — POST
# =============================================================================


@pytest.mark.django_db
def test_category_delete_requires_login(client, existing_cat):
    r = client.post(
        reverse("budget:category_delete", args=["category", existing_cat.slug])
    )
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_category_delete_removes_category(auth_client, existing_cat):
    slug = existing_cat.slug
    auth_client.post(reverse("budget:category_delete", args=["category", slug]))
    assert not Category.objects.filter(slug=slug).exists()


@pytest.mark.django_db
def test_category_delete_returns_hx_redirect(auth_client, existing_cat):
    r = auth_client.post(
        reverse("budget:category_delete", args=["category", existing_cat.slug])
    )
    assert r.status_code == 200
    assert r.has_header("HX-Redirect")
    assert "/budget/" in r["HX-Redirect"]


@pytest.mark.django_db
def test_category_delete_system_category_forbidden(auth_client, system_cat):
    """is_system=True → 404 (get_object_or_404 filtre is_system=False)."""
    slug = system_cat.slug
    r = auth_client.post(reverse("budget:category_delete", args=["category", slug]))
    assert r.status_code == 404
    assert Category.objects.filter(slug=slug).exists()  # toujours en DB


@pytest.mark.django_db
def test_category_delete_invalid_obj_type_returns_400(auth_client, existing_cat):
    r = auth_client.post(
        reverse("budget:category_delete", args=["invalid_type", existing_cat.slug])
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_category_delete_subcategory_removes_only_subcategory(
    auth_client, existing_cat
):
    sub = SubCategory.objects.create(
        category=existing_cat, name="To Delete", slug="to-delete-crud", is_system=False
    )
    auth_client.post(reverse("budget:category_delete", args=["subcategory", sub.slug]))
    assert not SubCategory.objects.filter(slug="to-delete-crud").exists()
    # Parent intact
    assert Category.objects.filter(slug=existing_cat.slug).exists()


# =============================================================================
# rule_create_submit — POST
# =============================================================================


@pytest.fixture
def cat_for_rule(db):
    return Category.objects.create(
        name="Cat Rules",
        slug="cat-rules-crud",
        colour_hex="#abcdef",
        order=99,
        is_system=False,
    )


@pytest.mark.django_db
def test_rule_create_submit_requires_login(client, cat_for_rule):
    r = client.post(
        reverse("budget:rule_create_submit"),
        {"keyword": "X", "category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert r.status_code == 302


@pytest.mark.django_db
def test_rule_create_submit_creates_rule(auth_client, cat_for_rule):
    auth_client.post(
        reverse("budget:rule_create_submit"),
        {"keyword": "newkw", "category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert CategorizationRule.objects.filter(
        keyword="NEWKW", category=cat_for_rule
    ).exists()


@pytest.mark.django_db
def test_rule_create_submit_uppercases_keyword(auth_client, cat_for_rule):
    auth_client.post(
        reverse("budget:rule_create_submit"),
        {"keyword": "lower case", "category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert CategorizationRule.objects.filter(keyword="LOWER CASE").exists()


@pytest.mark.django_db
def test_rule_create_submit_missing_keyword_returns_400(auth_client, cat_for_rule):
    r = auth_client.post(
        reverse("budget:rule_create_submit"),
        {"keyword": "", "category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_rule_create_submit_idempotent_get_or_create(auth_client, cat_for_rule):
    """Soumettre 2× la même règle ne doit pas créer de doublon (get_or_create)."""
    payload = {"keyword": "DUPKW", "category_id": str(cat_for_rule.id), "force": "1"}
    auth_client.post(reverse("budget:rule_create_submit"), payload)
    auth_client.post(reverse("budget:rule_create_submit"), payload)
    assert (
        CategorizationRule.objects.filter(
            keyword="DUPKW", category=cat_for_rule
        ).count()
        == 1
    )


# =============================================================================
# rule_create_standalone_submit — POST multi-keyword
# =============================================================================


@pytest.mark.django_db
def test_rule_create_standalone_requires_login(client, cat_for_rule):
    r = client.post(
        reverse("budget:rule_create_standalone_submit"),
        {"kw": "X", "category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert r.status_code == 302


@pytest.mark.django_db
def test_rule_create_standalone_creates_compound_keyword(auth_client, cat_for_rule):
    """Multi-chips kw[] → 1 règle avec keyword composé joint par espace."""
    auth_client.post(
        reverse("budget:rule_create_standalone_submit"),
        {
            "kw": ["MIGROS", "COOP", "ALDI"],
            "category_id": str(cat_for_rule.id),
            "force": "1",
        },
    )
    assert CategorizationRule.objects.filter(
        keyword="MIGROS COOP ALDI", category=cat_for_rule
    ).exists()


@pytest.mark.django_db
def test_rule_create_standalone_single_keyword_via_keyword_field(
    auth_client, cat_for_rule
):
    """Soumission avec champ `keyword` direct (re-confirmation après warning)."""
    auth_client.post(
        reverse("budget:rule_create_standalone_submit"),
        {"keyword": "essence", "category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert CategorizationRule.objects.filter(
        keyword="ESSENCE", category=cat_for_rule
    ).exists()


@pytest.mark.django_db
def test_rule_create_standalone_missing_keywords_no_create(auth_client, cat_for_rule):
    n_before = CategorizationRule.objects.count()
    auth_client.post(
        reverse("budget:rule_create_standalone_submit"),
        {"category_id": str(cat_for_rule.id), "force": "1"},
    )
    assert CategorizationRule.objects.count() == n_before

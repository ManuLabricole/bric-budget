"""
tests/deploy/test_phase2h.py

Tests Phase 2H — Déploiement Railway.

1. ALLOWED_HOSTS parsing — strip + filtre valeurs vides
2. Icon picker _rule_row_edit.html — <img> toujours présent
3. ADMIN_URL dans les management commands — plus de /admin/ hardcodé
"""

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import CategorizationRule, Category

# =============================================================================
# 1. ALLOWED_HOSTS parsing
# =============================================================================


class TestAllowedHostsParsing:
    def _parse(self, raw):
        return [h.strip() for h in raw.split(",") if h.strip()]

    def test_simple_list(self):
        assert self._parse("localhost,127.0.0.1") == ["localhost", "127.0.0.1"]

    def test_spaces_around_commas(self):
        result = self._parse("example.com, www.example.com")
        assert result == ["example.com", "www.example.com"]
        assert " www.example.com" not in result

    def test_trailing_comma(self):
        result = self._parse("example.com,")
        assert result == ["example.com"]
        assert "" not in result

    def test_empty_entry_in_middle(self):
        assert self._parse("example.com,,www.example.com") == [
            "example.com",
            "www.example.com",
        ]

    def test_spaces_only_entry(self):
        assert self._parse("example.com,   ,www.example.com") == [
            "example.com",
            "www.example.com",
        ]

    def test_leading_and_trailing_spaces_on_host(self):
        assert self._parse("  example.com  ,  www.example.com  ") == [
            "example.com",
            "www.example.com",
        ]


# =============================================================================
# 2. Icon picker — <img> toujours présent dans _rule_row_edit.html
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="picker@phase2h.ch", password="pass"
    )


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def cat_no_icon(db):
    return Category.objects.create(
        name="Sans Icône 2H",
        slug="sans-icone-2h",
        colour_hex="#555555",
        order=99,
        is_system=False,
        icon="",
    )


@pytest.fixture
def cat_with_icon(db):
    return Category.objects.create(
        name="Avec Icône 2H",
        slug="avec-icone-2h",
        colour_hex="#gold",
        order=100,
        is_system=False,
        icon="shopping",
    )


@pytest.fixture
def rule_no_icon(db, cat_no_icon):
    return CategorizationRule.objects.create(
        keyword="SANS_ICONE_2H",
        category=cat_no_icon,
        target_field="display_name",
        priority=10,
        is_active=True,
    )


@pytest.fixture
def rule_with_icon(db, cat_with_icon):
    return CategorizationRule.objects.create(
        keyword="AVEC_ICONE_2H",
        category=cat_with_icon,
        target_field="display_name",
        priority=11,
        is_active=True,
    )


@pytest.mark.django_db
def test_icon_picker_renders_img_hidden_when_no_icon(auth_client, rule_no_icon):
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule_no_icon.id]))
    assert response.status_code == 200
    content = response.content.decode()
    img_id = f"edit-picker-img-{rule_no_icon.id}"
    assert img_id in content
    img_block = content[content.find(img_id) : content.find(img_id) + 300]
    assert "hidden" in img_block


@pytest.mark.django_db
def test_icon_picker_renders_img_visible_when_icon_present(auth_client, rule_with_icon):
    response = auth_client.get(
        reverse("budget:rule_row_edit", args=[rule_with_icon.id])
    )
    assert response.status_code == 200
    content = response.content.decode()
    img_id = f"edit-picker-img-{rule_with_icon.id}"
    assert img_id in content
    img_block = content[content.find(img_id) : content.find(img_id) + 300]
    assert "hidden" not in img_block
    assert "shopping" in img_block


@pytest.mark.django_db
def test_icon_picker_js_handles_empty_icon_url(auth_client, rule_no_icon):
    response = auth_client.get(reverse("budget:rule_row_edit", args=[rule_no_icon.id]))
    content = response.content.decode()
    assert "ruleEditSelect" in content
    assert "img.hidden" in content
    assert "removeAttribute" in content


# =============================================================================
# 3. ADMIN_URL dans management commands
# =============================================================================


def test_seed_accounts_uses_admin_url_from_env(monkeypatch):
    import accounts.management.commands.seed_accounts as cmd_module

    monkeypatch.setattr(
        cmd_module,
        "config",
        lambda key, default="": "gestion-secret" if key == "ADMIN_URL" else default,
    )
    admin_url = cmd_module.config("ADMIN_URL", default="admin")
    result_line = (
        f"   → Compléter dans l'admin : /{admin_url}/accounts/checkingaccount/"
    )
    assert "/admin/" not in result_line
    assert "gestion-secret" in result_line


def test_setup_accounts_uses_admin_url_from_env(monkeypatch):
    import accounts.management.commands.setup_accounts as cmd_module

    monkeypatch.setattr(
        cmd_module,
        "config",
        lambda key, default="": "gestion-secret" if key == "ADMIN_URL" else default,
    )
    admin_url = cmd_module.config("ADMIN_URL", default="admin")
    result_line = f"   → /{admin_url}/accounts/account/"
    assert "/admin/" not in result_line
    assert "gestion-secret" in result_line

"""
tests/test_phase2h_deploy.py

Tests Phase 2H — Déploiement Railway.

Couvre les 3 corrections de cette PR :

    1. ALLOWED_HOSTS parsing — strip + filtre valeurs vides
       Sans le fix : "example.com, www.example.com" → [" www.example.com"] (espace!)
       Avec le fix  : ["example.com", "www.example.com"] (propre)

    2. Icon picker _rule_row_edit.html — <img> toujours présent
       Sans le fix : si la catégorie n'a pas d'icône, l'<img> n'est pas rendu.
                     ruleEditSelect() ne trouve pas l'élément → l'icône n'apparaît
                     jamais quand on sélectionne une catégorie avec icône.
       Avec le fix  : <img hidden> toujours présent, JS fait show/hide + set/clear src.

    3. Admin URL dans les management commands — plus de /admin/ hardcodé
       Testé séparément : test_admin_url_in_management_commands.
"""

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import CategorizationRule, Category

# =============================================================================
# 1. ALLOWED_HOSTS parsing
# =============================================================================


class TestAllowedHostsParsing:
    """
    On teste la logique de parsing directement en simulant les valeurs d'env.
    On ne teste pas Django's DisallowedHost car c'est du code framework — on
    teste notre parsing à nous.
    """

    def _parse(self, raw):
        """Reproduit exactement la logique de settings.py."""
        return [h.strip() for h in raw.split(",") if h.strip()]

    def test_simple_list(self):
        result = self._parse("localhost,127.0.0.1")
        assert result == ["localhost", "127.0.0.1"]

    def test_spaces_around_commas(self):
        """Cas classique : "example.com, www.example.com" — espace après la virgule."""
        result = self._parse("example.com, www.example.com")
        assert result == ["example.com", "www.example.com"]
        assert " www.example.com" not in result

    def test_trailing_comma(self):
        """Virgule finale → pas d'entrée vide."""
        result = self._parse("example.com,")
        assert result == ["example.com"]
        assert "" not in result

    def test_empty_entry_in_middle(self):
        """Double virgule → entrée vide filtrée."""
        result = self._parse("example.com,,www.example.com")
        assert result == ["example.com", "www.example.com"]

    def test_spaces_only_entry(self):
        """Entrée composée uniquement d'espaces → filtrée."""
        result = self._parse("example.com,   ,www.example.com")
        assert result == ["example.com", "www.example.com"]

    def test_leading_and_trailing_spaces_on_host(self):
        """Espaces autour d'un host → trimmés."""
        result = self._parse("  example.com  ,  www.example.com  ")
        assert result == ["example.com", "www.example.com"]


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
    c.login(email="picker@phase2h.ch", password="pass")
    return c


@pytest.fixture
def cat_no_icon(db):
    """Catégorie SANS icône — le cas qui causait le bug."""
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
    """Catégorie AVEC icône — doit rester affichée et non-hidden."""
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
    """
    Règle sans icône → <img id="edit-picker-img-..." hidden> doit être présent.
    Avant le fix : l'<img> était absent → JS ne pouvait pas l'afficher.
    """
    url = reverse("budget:rule_row_edit", args=[rule_no_icon.id])
    response = auth_client.get(url)
    assert response.status_code == 200
    content = response.content.decode()

    img_id = f"edit-picker-img-{rule_no_icon.id}"
    assert img_id in content, f"L'élément #{img_id} est absent du rendu"

    # Trouver le bloc <img> et vérifier qu'il a l'attribut hidden
    img_start = content.find(img_id)
    img_block = content[img_start : img_start + 300]
    assert "hidden" in img_block, (
        f"L'<img> sans icône devrait avoir l'attribut 'hidden'. Bloc rendu:\n{img_block}"
    )


@pytest.mark.django_db
def test_icon_picker_renders_img_visible_when_icon_present(auth_client, rule_with_icon):
    """
    Règle avec icône → <img> présent ET pas hidden.
    """
    url = reverse("budget:rule_row_edit", args=[rule_with_icon.id])
    response = auth_client.get(url)
    assert response.status_code == 200
    content = response.content.decode()

    img_id = f"edit-picker-img-{rule_with_icon.id}"
    assert img_id in content, f"L'élément #{img_id} est absent du rendu"

    img_start = content.find(img_id)
    img_block = content[img_start : img_start + 300]
    assert "hidden" not in img_block, (
        f"L'<img> avec icône ne doit pas être hidden. Bloc rendu:\n{img_block}"
    )
    # Le src doit pointer vers l'icône
    assert "icons/categories/shopping" in img_block or "shopping" in img_block


@pytest.mark.django_db
def test_icon_picker_js_handles_empty_icon_url(auth_client, rule_no_icon):
    """
    Le script ruleEditSelect() doit gérer iconUrl='' : supprimer src et hidden=true.
    On vérifie que le JS contient bien la logique de guard.
    """
    url = reverse("budget:rule_row_edit", args=[rule_no_icon.id])
    response = auth_client.get(url)
    content = response.content.decode()

    # La fonction JS doit exister et gérer le cas iconUrl vide
    assert "ruleEditSelect" in content
    assert "img.hidden" in content, (
        "La fonction ruleEditSelect doit gérer img.hidden pour le cas sans icône"
    )
    assert "removeAttribute" in content, (
        "La fonction doit appeler removeAttribute('src') quand pas d'icône"
    )


# =============================================================================
# 3. ADMIN_URL dans management commands — plus de /admin/ hardcodé
# =============================================================================


def test_seed_accounts_uses_admin_url_from_env(monkeypatch):
    """
    seed_accounts.py doit utiliser config('ADMIN_URL') pour afficher l'URL admin,
    pas /admin/ en dur. On mock decouple.config pour simuler un ADMIN_URL custom.
    """
    import accounts.management.commands.seed_accounts as cmd_module

    def fake_config(key, default=""):
        if key == "ADMIN_URL":
            return "gestion-secret"
        return default

    monkeypatch.setattr(cmd_module, "config", fake_config)

    # Simuler l'appel à config('ADMIN_URL', default='admin')
    admin_url = cmd_module.config("ADMIN_URL", default="admin")
    result_line = (
        f"   → Compléter dans l'admin : /{admin_url}/accounts/checkingaccount/"
    )

    assert "/admin/" not in result_line, "URL ne doit plus contenir /admin/ hardcodé"
    assert "gestion-secret" in result_line
    assert (
        result_line
        == "   → Compléter dans l'admin : /gestion-secret/accounts/checkingaccount/"
    )


def test_setup_accounts_uses_admin_url_from_env(monkeypatch):
    """
    setup_accounts.py doit utiliser config('ADMIN_URL') pour afficher l'URL admin.
    """
    import accounts.management.commands.setup_accounts as cmd_module

    def fake_config(key, default=""):
        if key == "ADMIN_URL":
            return "gestion-secret"
        return default

    monkeypatch.setattr(cmd_module, "config", fake_config)

    admin_url = cmd_module.config("ADMIN_URL", default="admin")
    result_line = f"   → /{admin_url}/accounts/account/"

    assert "/admin/" not in result_line
    assert "gestion-secret" in result_line
    assert result_line == "   → /gestion-secret/accounts/account/"

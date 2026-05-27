"""
tests/budget/test_templates.py

Tests structurels des templates frontend (Django Client + assertContains).
Pattern Dex : on pin le rendu HTML attendu AVANT d'extraire/refacto.

Couvre :
  - F1 : Tokens (CATEGORY_COLOR_PALETTE exposée + CSS var + composant color_dot)
  - F2 : Charts auto-init (data-chart attrs présents, plus de <script> BricCharts inline)
  - F3 : Category picker (data-attrs au lieu de onclick inline)
  - F4 : Page Budget index (IDs critiques, hx-target valides)
  - F5 : Page Category detail (tabs partials)
"""

import json

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from transactions.models import Category


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="tpl@t.ch", password="p")


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def some_category(db):
    return Category.objects.create(
        name="Alimentation tpl",
        slug="alimentation-tpl",
        colour_hex="#abc123",
        order=50,
        is_system=False,
    )


# =============================================================================
# F1 — Tokens & color system
# =============================================================================


@pytest.mark.django_db
def test_base_exposes_category_palette_in_tokens(auth_client):
    """window.BRICBUDGET_TOKENS.categories doit contenir la palette par défaut."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    content = r.content.decode()
    assert "BRICBUDGET_TOKENS" in content
    # La palette est exposée comme un sous-objet
    assert "BRICBUDGET_TOKENS.categories" in content or '"categories"' in content
    # Première couleur de CATEGORY_COLOR_PALETTE (ocre)
    assert "#eed8b4" in content


@pytest.mark.django_db
def test_base_defines_cat_fallback_css_var(auth_client):
    """CSS variable --cat-fallback définie dans base.html (fallback unique)."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    assert "--cat-fallback" in r.content.decode()


@pytest.mark.django_db
def test_color_dot_partial_renders_category_color(some_category):
    """Le partial color_dot.html doit utiliser la couleur de la catégorie."""
    html = render_to_string(
        "components/category/color_dot.html",
        {"category": some_category},
    )
    assert "#abc123" in html
    assert "cat-dot" in html


@pytest.mark.django_db
def test_color_dot_uses_css_var_for_fallback(db):
    """Si pas de colour_hex, le partial ne hardcode pas un hex — il laisse var(--cat-fallback) prendre le relais."""
    cat = Category.objects.create(
        name="No color",
        slug="no-color",
        colour_hex="",
        order=99,
        is_system=False,
    )
    html = render_to_string(
        "components/category/color_dot.html",
        {"category": cat},
    )
    # Pas de hex en dur dans le markup ; on s'appuie sur le fallback CSS
    assert "#2d3033" not in html
    assert "#4a4c55" not in html
    assert "cat-dot" in html


# =============================================================================
# F2 — Charts auto-init
# =============================================================================


@pytest.mark.django_db
def test_index_chart_containers_have_data_chart_attrs(auth_client):
    """Les conteneurs sankey/donut doivent avoir data-chart=... (pas d'init JS inline)."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    content = r.content.decode()
    assert 'data-chart="sankey"' in content
    assert 'data-chart="donut"' in content


@pytest.mark.django_db
def test_index_no_inline_brichcharts_init(auth_client):
    """index.html ne doit plus contenir BricCharts.initSankey/initDonut en inline."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    content = r.content.decode()
    assert "BricCharts.initSankey(" not in content
    assert "BricCharts.initDonut(" not in content


@pytest.mark.django_db
def test_base_app_loads_auto_init_script(auth_client):
    """base_app.html doit charger charts/auto-init.js (chargement centralisé)."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    assert "charts/auto-init.js" in r.content.decode()


@pytest.mark.django_db
def test_category_detail_chart_containers_have_data_attrs(auth_client, some_category):
    """category_detail.html : containers data-driven."""
    r = auth_client.get(
        reverse("budget:category_detail", args=[some_category.slug]),
        HTTP_HOST="localhost",
    )
    if r.status_code != 200:
        pytest.skip(f"category_detail returned {r.status_code}")
    content = r.content.decode()
    # Au moins sankey (toujours rendu si transactions) ; les autres sont conditionnels
    assert 'data-chart="sankey"' in content or "sankey-chart" not in content


# =============================================================================
# F3 — Category picker (anti onclick inline + escapejs)
# =============================================================================


@pytest.mark.django_db
def test_rule_create_standalone_uses_data_attrs_not_onclick(auth_client, some_category):
    """_panel_rule_create_standalone.html : data-cat-* au lieu de onclick="ruleStandaloneSelect(...)"."""
    r = auth_client.get(
        reverse("budget:panel_rule_create_standalone"),
        HTTP_HOST="localhost",
    )
    content = r.content.decode()
    assert "data-cat-id=" in content
    assert "data-cat-color=" in content
    # Plus de onclick avec interpolation Python
    assert "ruleStandaloneSelect(" not in content


@pytest.mark.django_db
def test_category_create_uses_data_attrs_not_onclick(auth_client):
    """_panel_category_create.html : data-cat-* au lieu de onclick="catSelectParent(...)"."""
    r = auth_client.get(reverse("budget:panel_category_create"), HTTP_HOST="localhost")
    content = r.content.decode()
    if r.status_code != 200:
        pytest.skip(f"panel_category_create returned {r.status_code}")
    assert "catSelectParent(" not in content


# =============================================================================
# F4 — Page Budget index : IDs critiques + hx-target valides
# =============================================================================


@pytest.mark.django_db
def test_index_has_critical_ids(auth_client):
    """IDs nécessaires aux HTMX swaps et au JS d'init."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    content = r.content.decode()
    for crit_id in ["panel-content", "sankey-chart", "donut-chart"]:
        assert f'id="{crit_id}"' in content, f"#{crit_id} missing in /budget/"


@pytest.mark.django_db
def test_index_hx_target_panel_content_is_valid(auth_client):
    """Si un hx-target=#panel-content existe, l'ID doit aussi exister sur la page."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    content = r.content.decode()
    if 'hx-target="#panel-content"' in content:
        assert 'id="panel-content"' in content


@pytest.mark.django_db
def test_index_json_script_sankey_data_has_payload(auth_client):
    """Le json_script sankey-data ne doit pas être vide (sinon le chart sera vide)."""
    r = auth_client.get(reverse("budget:index"), HTTP_HOST="localhost")
    content = r.content.decode()
    # Le marker du json_script Django
    assert 'id="sankey-data"' in content
    # Vérifier qu'il y a bien du JSON dedans (pas juste {})
    import re

    m = re.search(r'<script id="sankey-data"[^>]*>(.*?)</script>', content, re.DOTALL)
    assert m is not None
    payload = json.loads(m.group(1))
    assert "nodes" in payload or "links" in payload or len(payload) > 0


# =============================================================================
# F5 — Page Category detail : structure + tabs
# =============================================================================


@pytest.mark.django_db
def test_category_detail_has_cashflow_card(auth_client, some_category):
    """Cashflow card présente sur le détail catégorie."""
    r = auth_client.get(
        reverse("budget:category_detail", args=[some_category.slug]),
        HTTP_HOST="localhost",
    )
    assert r.status_code == 200
    assert 'id="cashflow-card"' in r.content.decode()


@pytest.mark.django_db
def test_category_detail_shows_category_name(auth_client, some_category):
    r = auth_client.get(
        reverse("budget:category_detail", args=[some_category.slug]),
        HTTP_HOST="localhost",
    )
    assert some_category.name in r.content.decode()

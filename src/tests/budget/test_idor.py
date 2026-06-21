"""
tests/budget/test_idor.py

Protection IDOR sur toutes les vues budget/ :
  - transactions : toggle_ignore, panel_tx_detail, categorize, rule_create, rule_preview, toggle_reconcile
  - dropdowns comptes : budget_index, panel_transactions, category_detail
  - comptages catégories : panel_category_manage, category_manage_detail, category_delete_confirm
  - rule_edit_submit : entrée non numérique → 200, règle inchangée
"""

import hashlib
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from transactions.models import (
    CategorizationRule,
    Category,
    SubCategory,
    Transaction,
)

# =============================================================================
# Helpers
# =============================================================================


def make_tx(account, seed):
    return Transaction.objects.create(
        account=account,
        date="2026-01-15",
        amount=-20,
        currency="CHF",
        amount_chf=-20,
        description_raw=f"TX IDOR {seed}",
        display_name=f"TX IDOR {seed}",
        import_hash=hashlib.sha256(f"idor:{seed}".encode()).hexdigest(),
    )


def _make_txs(account, category, subcat=None, n=1):
    from datetime import date

    Transaction.objects.bulk_create(
        [
            Transaction(
                account=account,
                category=category,
                subcategory=subcat,
                amount=Decimal("-10.00"),
                date=date(2026, 1, 1),
                description_raw=f"tx-{i}",
                import_hash=f"hash-{account.pk}-{category.pk}-{i}-{subcat.pk if subcat else 'x'}",
            )
            for i in range(n)
        ]
    )


# =============================================================================
# Vues transactions — user B ne peut pas accéder aux tx de user A
# =============================================================================


@pytest.mark.django_db
def test_idor_toggle_ignore_blocked_for_other_user(client_b, account_a):
    tx = make_tx(account_a, "ignore-block")
    response = client_b.post(reverse("budget:toggle_ignore", args=[tx.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_toggle_ignore_allowed_for_owner(client_a, account_a):
    tx = make_tx(account_a, "ignore-allow")
    response = client_a.post(reverse("budget:toggle_ignore", args=[tx.pk]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_idor_panel_tx_detail_blocked_for_other_user(client_b, account_a):
    tx = make_tx(account_a, "detail-block")
    response = client_b.get(reverse("budget:panel_tx_detail") + f"?tx_id={tx.pk}")
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_panel_tx_detail_allowed_for_owner(client_a, account_a):
    tx = make_tx(account_a, "detail-allow")
    response = client_a.get(reverse("budget:panel_tx_detail") + f"?tx_id={tx.pk}")
    assert response.status_code == 200


@pytest.mark.django_db
def test_idor_categorize_blocked_for_other_user(client_b, account_a, category):
    tx = make_tx(account_a, "cat-block")
    response = client_b.post(
        reverse("budget:categorize"),
        {"tx_id": tx.pk, "category_id": category.pk},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_categorize_allowed_for_owner(client_a, account_a, category):
    tx = make_tx(account_a, "cat-allow")
    response = client_a.post(
        reverse("budget:categorize"),
        {"tx_id": tx.pk, "category_id": category.pk},
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_idor_panel_rule_create_blocked_for_other_user(client_b, account_a, category):
    tx = make_tx(account_a, "rule-block")
    response = client_b.get(
        reverse("budget:panel_rule_create") + f"?tx_id={tx.pk}&keyword=TEST"
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_panel_rule_create_allowed_for_owner(client_a, account_a, category):
    tx = make_tx(account_a, "rule-allow")
    response = client_a.get(
        reverse("budget:panel_rule_create") + f"?tx_id={tx.pk}&keyword=TEST"
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_idor_rule_preview_blocked_for_other_user(client_b, account_a, category):
    tx = make_tx(account_a, "preview-block")
    response = client_b.post(
        reverse("budget:rule_preview"),
        {"tx_id": tx.pk, "keyword": "TEST", "category_id": category.pk},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_toggle_reconcile_blocked_for_other_user(client_b, account_a):
    tx = make_tx(account_a, "reconcile-block")
    response = client_b.post(reverse("budget:toggle_reconcile", args=[tx.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_toggle_reconcile_allowed_for_owner(client_a, account_a):
    tx = make_tx(account_a, "reconcile-allow")
    response = client_a.post(reverse("budget:toggle_reconcile", args=[tx.pk]))
    assert response.status_code == 200


# =============================================================================
# Dropdowns comptes — user B ne doit pas apparaître dans les dropdowns de user A
# =============================================================================


@pytest.mark.django_db
def test_budget_index_shows_own_account_in_dropdown(client_a, account_a, account_b):
    response = client_a.get(reverse("budget:index"))
    assert response.status_code == 200
    assert "COMPTE EXCLUSIF USER A" in response.content.decode()


@pytest.mark.django_db
def test_budget_index_hides_other_user_account_from_dropdown(
    client_a, account_a, account_b
):
    response = client_a.get(reverse("budget:index"))
    assert "COMPTE EXCLUSIF USER B" not in response.content.decode()


@pytest.mark.django_db
def test_panel_transactions_shows_own_account_in_dropdown(
    client_a, account_a, account_b
):
    response = client_a.get(reverse("budget:panel_transactions"))
    assert response.status_code == 200
    assert "COMPTE EXCLUSIF USER A" in response.content.decode()


@pytest.mark.django_db
def test_panel_transactions_hides_other_user_account_from_dropdown(
    client_a, account_a, account_b
):
    response = client_a.get(reverse("budget:panel_transactions"))
    assert "COMPTE EXCLUSIF USER B" not in response.content.decode()


@pytest.mark.django_db
def test_category_detail_shows_own_account_in_dropdown(
    client_a, account_a, account_b, category
):
    response = client_a.get(reverse("budget:category_detail", args=[category.slug]))
    assert response.status_code == 200
    assert "COMPTE EXCLUSIF USER A" in response.content.decode()


@pytest.mark.django_db
def test_category_detail_hides_other_user_account_from_dropdown(
    client_a, account_a, account_b, category
):
    response = client_a.get(reverse("budget:category_detail", args=[category.slug]))
    assert "COMPTE EXCLUSIF USER B" not in response.content.decode()


# =============================================================================
# Comptages catégories — tx_count scopé à l'user connecté
# =============================================================================


@pytest.mark.django_db
def test_category_manage_tx_count_includes_only_own_transactions(
    client_a, account_a, account_b, category, user_b
):
    _make_txs(account_a, category, n=3)
    _make_txs(account_b, category, n=5)
    response = client_a.get(reverse("budget:panel_category_manage"))
    assert response.status_code == 200
    cat = next(c for c in response.context["cats"] if c.slug == category.slug)
    assert cat.tx_count == 3


@pytest.mark.django_db
def test_category_manage_tx_count_excludes_other_user_transactions(
    client_a, account_a, account_b, category
):
    _make_txs(account_b, category, n=10)
    response = client_a.get(reverse("budget:panel_category_manage"))
    cat = next(c for c in response.context["cats"] if c.slug == category.slug)
    assert cat.tx_count == 0


@pytest.mark.django_db
def test_category_manage_detail_subcat_tx_count_scoped_to_user(
    client_a, account_a, account_b, category, subcat
):
    _make_txs(account_a, category, subcat=subcat, n=2)
    _make_txs(account_b, category, subcat=subcat, n=7)
    response = client_a.get(
        reverse("budget:panel_category_manage_detail", args=[category.slug])
    )
    assert response.status_code == 200
    sc = next(s for s in response.context["subcats"] if s.slug == subcat.slug)
    assert sc.tx_count == 2


@pytest.mark.django_db
def test_category_manage_detail_subcat_tx_count_zero_for_other_user(
    client_a, account_a, account_b, category, subcat
):
    _make_txs(account_b, category, subcat=subcat, n=4)
    response = client_a.get(
        reverse("budget:panel_category_manage_detail", args=[category.slug])
    )
    sc = next(s for s in response.context["subcats"] if s.slug == subcat.slug)
    assert sc.tx_count == 0


@pytest.mark.django_db
def test_category_delete_confirm_tx_count_scoped_to_user(
    client_a, account_a, account_b, category
):
    _make_txs(account_a, category, n=4)
    _make_txs(account_b, category, n=6)
    response = client_a.get(
        reverse("budget:category_delete_confirm", args=["category", category.slug])
    )
    assert response.status_code == 200
    assert response.context["tx_count"] == 4


@pytest.mark.django_db
def test_category_delete_confirm_does_not_count_other_user_transactions(
    client_a, account_a, account_b, category
):
    _make_txs(account_b, category, n=8)
    response = client_a.get(
        reverse("budget:category_delete_confirm", args=["category", category.slug])
    )
    assert response.context["tx_count"] == 0


@pytest.mark.django_db
def test_subcategory_delete_confirm_tx_count_scoped_to_user(
    client_a, account_a, account_b, category, subcat
):
    _make_txs(account_a, category, subcat=subcat, n=3)
    _make_txs(account_b, category, subcat=subcat, n=9)
    response = client_a.get(
        reverse("budget:category_delete_confirm", args=["subcategory", subcat.slug])
    )
    assert response.context["tx_count"] == 3


# =============================================================================
# Catégories scopées par owner (#137) — un user ne voit pas les perso d'un autre
# =============================================================================


@pytest.mark.django_db
def test_category_for_user_returns_system_and_own_only(
    system_category, category_a, category_b, user_a
):
    """Manager .for_user : système (owner NULL) OU à moi ; jamais la perso d'un autre."""
    visible = set(Category.objects.for_user(user_a).values_list("slug", flat=True))
    assert system_category.slug in visible  # système → visible
    assert category_a.slug in visible  # ma perso → visible
    assert category_b.slug not in visible  # perso d'un autre → INVISIBLE


@pytest.mark.django_db
def test_subcategory_for_user_excludes_other_user_perso(subcat_b, user_a):
    visible = set(SubCategory.objects.for_user(user_a).values_list("slug", flat=True))
    assert subcat_b.slug not in visible


@pytest.mark.django_db
def test_category_manage_lists_own_perso_not_other_user(
    client_a, category_a, category_b
):
    """Le panel de gestion ne liste que système + perso du user connecté."""
    response = client_a.get(reverse("budget:panel_category_manage"))
    assert response.status_code == 200
    slugs = {c.slug for c in response.context["cats"]}
    assert category_a.slug in slugs
    assert category_b.slug not in slugs
    # Défense en profondeur : le nom de la perso d'un autre ne fuit pas dans le HTML.
    assert "PERSO USER B CATEGORY" not in response.content.decode()


@pytest.mark.django_db
def test_category_manage_detail_other_user_perso_returns_404(client_a, category_b):
    """Accéder au détail d'une perso d'un autre user → 404 (pas de fuite)."""
    response = client_a.get(
        reverse("budget:panel_category_manage_detail", args=[category_b.slug])
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_manage_detail_own_perso_ok(client_a, category_a):
    response = client_a.get(
        reverse("budget:panel_category_manage_detail", args=[category_a.slug])
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_category_picker_hides_other_user_perso(client_a, account_a, category_b):
    """Le picker de catégorie (custom_cats) ne montre pas la perso d'un autre user."""
    tx = make_tx(account_a, "picker-scope")
    response = client_a.get(reverse("budget:panel_category_picker") + f"?tx_id={tx.pk}")
    assert response.status_code == 200
    custom_slugs = {c.slug for c in response.context["custom_cats"]}
    assert category_b.slug not in custom_slugs
    assert "PERSO USER B CATEGORY" not in response.content.decode()


@pytest.mark.django_db
def test_categorize_with_other_user_perso_category_blocked(
    client_a, account_a, category_b
):
    """POST categorize avec la perso d'un AUTRE user → 404, tx non catégorisée."""
    tx = make_tx(account_a, "cat-foreign-perso")
    response = client_a.post(
        reverse("budget:categorize"),
        {"tx_id": tx.pk, "category_id": category_b.pk},
    )
    assert response.status_code == 404
    tx.refresh_from_db()
    assert tx.category_id is None


@pytest.mark.django_db
def test_categorize_with_own_perso_category_allowed(client_a, account_a, category_a):
    tx = make_tx(account_a, "cat-own-perso")
    response = client_a.post(
        reverse("budget:categorize"),
        {"tx_id": tx.pk, "category_id": category_a.pk},
    )
    assert response.status_code == 200
    tx.refresh_from_db()
    assert tx.category_id == category_a.pk


@pytest.mark.django_db
def test_subcategory_create_under_other_user_perso_parent_blocked(client_a, category_b):
    """Créer une sous-cat sous la catégorie perso d'un AUTRE user → bloqué (404)."""
    response = client_a.post(
        reverse("budget:category_create_submit"),
        {
            "cat_type": "sub",
            "name": "Tentative IDOR",
            "icon": "heartbeat",
            "parent_id": str(category_b.pk),
        },
    )
    assert response.status_code == 404
    assert not SubCategory.objects.filter(name="Tentative IDOR").exists()


@pytest.mark.django_db
def test_two_users_can_each_create_restaurants_via_view(
    client_a, client_b, user_a, user_b
):
    """
    Acceptance #137 via la vue réelle : user A puis user B créent chacun une
    catégorie « Restaurants ». Les DEUX doivent réussir (succès = status 200 +
    objet en DB avec le bon owner). C'est le scénario tranché avec Emmanuel.
    """
    payload = {
        "cat_type": "main",
        "name": "Restaurants",
        "icon": "heartbeat",
        "colour_hex": "#e77f79",
    }
    r_a = client_a.post(reverse("budget:category_create_submit"), payload)
    r_b = client_b.post(reverse("budget:category_create_submit"), payload)
    assert r_a.status_code == 200
    assert r_b.status_code == 200

    cat_a = Category.objects.get(name="Restaurants", owner=user_a)
    cat_b = Category.objects.get(name="Restaurants", owner=user_b)
    assert cat_a.pk != cat_b.pk
    assert cat_a.is_system is False and cat_b.is_system is False
    # Le slug perso n'est PAS suffixé à cause de l'autre user (scope par owner).
    assert cat_a.slug == "restaurants"
    assert cat_b.slug == "restaurants"


@pytest.mark.django_db
def test_same_user_cannot_create_duplicate_category_via_view(client_a, user_a):
    """Le même user qui retape « Restaurants » est bloqué côté vue (message d'erreur)."""
    payload = {
        "cat_type": "main",
        "name": "Restaurants",
        "icon": "heartbeat",
        "colour_hex": "#e77f79",
    }
    first = client_a.post(reverse("budget:category_create_submit"), payload)
    assert first.status_code == 200
    second = client_a.post(reverse("budget:category_create_submit"), payload)
    assert second.status_code == 200  # re-render du panel avec erreur, pas un 500
    assert Category.objects.filter(name="Restaurants", owner=user_a).count() == 1


@pytest.mark.django_db
def test_category_create_sets_owner_to_request_user(client_a, user_a):
    """Une catégorie créée via l'UI appartient au créateur (owner=request.user)."""
    response = client_a.post(
        reverse("budget:category_create_submit"),
        {
            "cat_type": "main",
            "name": "Ma Catégorie Perso",
            "icon": "heartbeat",
            "colour_hex": "#e77f79",
        },
    )
    assert response.status_code == 200
    cat = Category.objects.get(name="Ma Catégorie Perso")
    assert cat.owner_id == user_a.pk
    assert cat.is_system is False


# =============================================================================
# CategorizationRule scopée par owner (#145) — IDOR sur les vues CRUD règles
#
# Un user authentifié ne doit PAS pouvoir toggle / éditer / supprimer / lister
# une règle appartenant à un autre user via un POST/GET forgé (SR-001).
# Pattern : .for_user() retourne système (owner NULL) OU à moi ; jamais la perso
# d'un autre → get_object_or_404 renvoie 404 pour l'attaquant, 200 pour l'owner.
# =============================================================================


@pytest.mark.django_db
def test_idor_rule_toggle_blocked_for_other_user(client_b, rule_a):
    """user B toggle une règle de user A → 404 (et l'état n'a pas changé)."""
    response = client_b.post(reverse("budget:rule_toggle_active", args=[rule_a.id]))
    assert response.status_code == 404
    rule_a.refresh_from_db()
    assert rule_a.is_active is True  # non modifiée


@pytest.mark.django_db
def test_idor_rule_toggle_allowed_for_owner(client_a, rule_a):
    response = client_a.post(reverse("budget:rule_toggle_active", args=[rule_a.id]))
    assert response.status_code == 200
    rule_a.refresh_from_db()
    assert rule_a.is_active is False


@pytest.mark.django_db
def test_idor_rule_delete_blocked_for_other_user(client_b, rule_a):
    """user B supprime une règle de user A → 404 (la règle existe toujours)."""
    response = client_b.post(reverse("budget:rule_delete", args=[rule_a.id]))
    assert response.status_code == 404
    assert CategorizationRule.objects.filter(id=rule_a.id).exists()


@pytest.mark.django_db
def test_idor_rule_delete_allowed_for_owner(client_a, rule_a):
    response = client_a.post(reverse("budget:rule_delete", args=[rule_a.id]))
    assert response.status_code == 200
    assert not CategorizationRule.objects.filter(id=rule_a.id).exists()


@pytest.mark.django_db
def test_idor_rule_row_edit_blocked_for_other_user(client_b, rule_a):
    """user B ouvre le formulaire d'édition d'une règle de user A → 404."""
    response = client_b.get(reverse("budget:rule_row_edit", args=[rule_a.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_idor_rule_row_edit_allowed_for_owner(client_a, rule_a):
    response = client_a.get(reverse("budget:rule_row_edit", args=[rule_a.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_idor_rule_edit_submit_blocked_for_other_user(client_b, rule_a, category):
    """user B sauvegarde l'édition d'une règle de user A → 404 (rien n'a changé)."""
    response = client_b.post(
        reverse("budget:rule_edit_submit", args=[rule_a.id]),
        {"keyword": "HACKED", "category_id": category.id},
    )
    assert response.status_code == 404
    rule_a.refresh_from_db()
    assert rule_a.keyword == "RULE-OWNED-BY-A"


@pytest.mark.django_db
def test_idor_rule_edit_submit_allowed_for_owner(client_a, rule_a, category):
    response = client_a.post(
        reverse("budget:rule_edit_submit", args=[rule_a.id]),
        {"keyword": "RENAMED", "category_id": category.id},
    )
    assert response.status_code == 200
    rule_a.refresh_from_db()
    assert rule_a.keyword == "RENAMED"


@pytest.mark.django_db
def test_rule_for_user_returns_own_and_system_not_other(rule_a, rule_b, user_a):
    """Manager .for_user : ma règle + règles système (owner NULL), jamais la perso d'un autre."""
    visible = set(
        CategorizationRule.objects.for_user(user_a).values_list("keyword", flat=True)
    )
    assert "RULE-OWNED-BY-A" in visible  # ma règle → visible
    assert "RULE-OWNED-BY-B" not in visible  # règle d'un autre → INVISIBLE


@pytest.mark.django_db
def test_panel_rules_list_hides_other_user_rule(client_a, rule_a, rule_b):
    """Le panel CRUD ne liste que système + règles du user connecté (pas la perso d'un autre)."""
    response = client_a.get(reverse("budget:panel_rules_list"))
    assert response.status_code == 200
    keywords = {r.keyword for r in response.context["rules"]}
    assert "RULE-OWNED-BY-A" in keywords
    assert "RULE-OWNED-BY-B" not in keywords
    # Défense en profondeur : la règle d'un autre ne fuit pas dans le HTML.
    assert "RULE-OWNED-BY-B" not in response.content.decode()


@pytest.mark.django_db
def test_export_rules_excludes_other_user_rule(client_a, rule_a, rule_b):
    """L'export JSON ne contient pas les règles d'un autre user."""
    response = client_a.get(
        reverse("budget:export_rules_download"), HTTP_HOST="localhost"
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "RULE-OWNED-BY-A" in body
    assert "RULE-OWNED-BY-B" not in body


@pytest.mark.django_db
def test_rule_create_submit_sets_owner_to_request_user(client_a, account_a, category):
    """Une règle créée via l'UI appartient au créateur (owner=request.user)."""
    tx = make_tx(account_a, "rule-owner-create")
    response = client_a.post(
        reverse("budget:rule_create_submit"),
        {
            "tx_id": tx.pk,
            "keyword": "OWNERCHECK",
            "category_id": category.pk,
            "force": "1",
        },
    )
    assert response.status_code == 200
    rule = CategorizationRule.objects.get(keyword="OWNERCHECK")
    assert rule.owner_id == account_a.members.first().pk


@pytest.mark.django_db
def test_rule_create_standalone_sets_owner_to_request_user(client_a, user_a, category):
    """Règle standalone créée via l'UI appartient au créateur (owner=request.user)."""
    response = client_a.post(
        reverse("budget:rule_create_standalone_submit"),
        {"keyword": "STANDALONEOWNER", "category_id": category.pk, "force": "1"},
    )
    assert response.status_code == 200
    rule = CategorizationRule.objects.get(keyword="STANDALONEOWNER")
    assert rule.owner_id == user_a.pk


# =============================================================================
# rule_edit_submit — entrée non numérique → 200, règle inchangée
# =============================================================================


@pytest.fixture
def rule_for_edit(db, category, user_a):
    return CategorizationRule.objects.create(
        keyword="SUPERMARCHE",
        category=category,
        priority=10,
        owner=user_a,
    )


@pytest.mark.django_db
def test_rule_edit_non_numeric_category_id_returns_rule_unchanged(
    client_a, rule_for_edit, category
):
    response = client_a.post(
        reverse("budget:rule_edit_submit", args=[rule_for_edit.id]),
        {"keyword": "NEWKW", "category_id": "not-a-number", "subcategory_id": ""},
    )
    assert response.status_code == 200
    rule_for_edit.refresh_from_db()
    assert rule_for_edit.keyword == "SUPERMARCHE"
    assert rule_for_edit.category_id == category.pk


@pytest.mark.django_db
def test_rule_edit_non_numeric_subcategory_id_returns_rule_unchanged(
    client_a, rule_for_edit, category
):
    response = client_a.post(
        reverse("budget:rule_edit_submit", args=[rule_for_edit.id]),
        {
            "keyword": "NEWKW",
            "category_id": str(category.pk),
            "subcategory_id": "not-a-number",
        },
    )
    assert response.status_code == 200
    rule_for_edit.refresh_from_db()
    assert rule_for_edit.keyword == "SUPERMARCHE"


# =============================================================================
# Settings IMPORT_ENCRYPTION_KEY
# =============================================================================


def test_settings_without_import_encryption_key_does_not_crash():
    from django.conf import settings

    key = getattr(settings, "IMPORT_ENCRYPTION_KEY", None)
    assert key is not None
    assert isinstance(key, str)


def test_storage_get_fernet_raises_improperly_configured_when_empty():
    from django.core.exceptions import ImproperlyConfigured

    from imports.storage import _get_fernet

    with override_settings(IMPORT_ENCRYPTION_KEY=""):
        with pytest.raises(ImproperlyConfigured) as exc_info:
            _get_fernet()
        assert "IMPORT_ENCRYPTION_KEY" in str(exc_info.value)

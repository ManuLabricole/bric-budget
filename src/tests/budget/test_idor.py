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

from transactions.models import CategorizationRule, Transaction

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
# rule_edit_submit — entrée non numérique → 200, règle inchangée
# =============================================================================


@pytest.fixture
def rule_for_edit(db, category):
    return CategorizationRule.objects.create(
        keyword="SUPERMARCHE",
        category=category,
        priority=10,
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

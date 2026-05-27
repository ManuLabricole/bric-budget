"""
tests/budget/test_views.py

Tests des vues budget/ :
  - Auth : toutes les vues @login_required redirigent en 302 pour user non connecté
  - Category cashflow fragment + page detail
"""

import hashlib
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from transactions.models import Category, Transaction

# =============================================================================
# Fixtures locales (cashflow — scope narrow, pas dans conftest)
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="views@budget.ch", password="pass"
    )


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="other-views@budget.ch", password="pass"
    )


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def other_client(other_user):
    c = Client()
    c.force_login(other_user)
    return c


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(
        name="Views Budget Bank",
        slug="views-budget-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    from accounts.models import Account

    acc = Account.objects.create(
        bank=bank,
        name="Views Budget Account",
        account_type="checking",
        currency="CHF",
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def some_category(db):
    return Category.objects.create(
        name="Views Test Cat",
        slug="views-test-cat",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


@pytest.fixture
def some_rule(db, some_category):
    from transactions.models import CategorizationRule

    return CategorizationRule.objects.create(
        keyword="VIEWSTEST",
        category=some_category,
        target_field="display_name",
        priority=1,
        is_active=True,
    )


def make_tx(account, category, amount="-50.00", seed="cf"):
    from datetime import date

    return Transaction.objects.create(
        account=account,
        category=category,
        date=date.today().replace(day=1),
        amount=Decimal(amount),
        currency="CHF",
        amount_chf=Decimal(amount),
        description_raw=f"CF TX {seed}",
        display_name=f"CF TX {seed}",
        is_ignored=False,
        import_hash=hashlib.sha256(f"cf-test:{seed}".encode()).hexdigest(),
    )


# =============================================================================
# Auth — vues budget/ sans paramètre
# =============================================================================


@pytest.mark.django_db
def test_budget_index_requires_login(client):
    response = client.get(reverse("budget:index"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_panel_transactions_requires_login(client):
    response = client.get(reverse("budget:panel_transactions"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_panel_rules_list_requires_login(client):
    response = client.get(reverse("budget:panel_rules_list"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_export_rules_requires_login(client):
    response = client.get(reverse("budget:export_rules_download"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_toggle_decimals_requires_login(client):
    response = client.post(reverse("budget:toggle_decimals"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


# =============================================================================
# Auth — vues budget/ avec paramètre slug ou pk
# =============================================================================


@pytest.mark.django_db
def test_budget_category_detail_requires_login(client, some_category):
    response = client.get(reverse("budget:category_detail", args=[some_category.slug]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_category_cashflow_fragment_requires_login(client, some_category):
    response = client.get(
        reverse("budget:category_cashflow_fragment", args=[some_category.slug])
    )
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_rule_toggle_active_requires_login(client, some_rule):
    response = client.post(reverse("budget:rule_toggle_active", args=[some_rule.id]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_rule_delete_requires_login(client, some_rule):
    response = client.post(reverse("budget:rule_delete", args=[some_rule.id]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_budget_rule_row_edit_requires_login(client, some_rule):
    response = client.get(reverse("budget:rule_row_edit", args=[some_rule.id]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


# =============================================================================
# Category cashflow fragment
# =============================================================================


@pytest.fixture
def cf_category(db):
    return Category.objects.create(
        name="Alimentation CF",
        slug="alimentation-cf",
        colour_hex="#4ade80",
        order=50,
        is_system=False,
    )


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_200(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_inner_html_only(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content


@pytest.mark.django_db
def test_category_cashflow_fragment_contains_cashflow_header(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert "Cashflow" in response.content.decode()


@pytest.mark.django_db
def test_category_cashflow_fragment_returns_404_for_unknown_slug(auth_client):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=["slug-qui-nexiste-pas"])
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_cashflow_fragment_no_sankey_without_transactions(
    auth_client, cf_category
):
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert 'id="sankey-chart"' not in response.content.decode()


@pytest.mark.django_db
def test_category_cashflow_fragment_shows_sankey_with_active_transactions(
    auth_client, account, cf_category
):
    make_tx(account, cf_category, seed="sankey-ok")
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert 'id="sankey-chart"' in content
    assert 'id="sankey-data"' in content


@pytest.mark.django_db
def test_category_cashflow_fragment_ignored_txs_excluded_from_total(
    auth_client, account, cf_category
):
    make_tx(account, cf_category, amount="-100.00", seed="active")
    ignored_tx = make_tx(account, cf_category, amount="-999.00", seed="ignored")
    ignored_tx.is_ignored = True
    ignored_tx.save(update_fields=["is_ignored"])
    response = auth_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "999" not in content or "100" in content


@pytest.mark.django_db
def test_category_cashflow_fragment_other_user_sees_zero_total(
    other_client, account, cf_category
):
    make_tx(account, cf_category, amount="-500.00", seed="other-idor")
    response = other_client.get(
        reverse("budget:category_cashflow_fragment", args=[cf_category.slug])
    )
    assert response.status_code == 200
    assert "500" not in response.content.decode()


# =============================================================================
# Category detail page
# =============================================================================


@pytest.mark.django_db
def test_category_detail_returns_200(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_category_detail_returns_full_page(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert "<!DOCTYPE html>" in content or "<html" in content


@pytest.mark.django_db
def test_category_detail_returns_404_for_unknown_slug(auth_client):
    response = auth_client.get(reverse("budget:category_detail", args=["slug-inconnu"]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_category_detail_no_sankey_without_transactions(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert 'id="sankey-chart"' not in response.content.decode()


@pytest.mark.django_db
def test_category_detail_shows_sankey_with_transactions(
    auth_client, account, cf_category
):
    make_tx(account, cf_category, seed="detail-sankey")
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    content = response.content.decode()
    assert 'id="sankey-chart"' in content


@pytest.mark.django_db
def test_category_detail_shows_category_name(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert cf_category.name in response.content.decode()


@pytest.mark.django_db
def test_category_detail_contains_cashflow_card(auth_client, cf_category):
    response = auth_client.get(
        reverse("budget:category_detail", args=[cf_category.slug])
    )
    assert 'id="cashflow-card"' in response.content.decode()

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
    from accounts.models import Institution

    return Institution.objects.create(
        name="Views Budget Bank",
        slug="views-budget-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=bank,
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


# =============================================================================
# Panel transactions — filtre catégories blacklist
# =============================================================================


@pytest.mark.django_db
def test_panel_transactions_excludes_hidden_categories(
    auth_client, account, cf_category
):
    """Le panel exclut les transactions des catégories masquées en session."""
    from datetime import date

    tx = Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-30.00"),
        currency="CHF",
        amount_chf=Decimal("-30.00"),
        description_raw="EXCLUDED BY CAT FILTER",
        display_name="EXCLUDED BY CAT FILTER",
        import_hash="panel_hidden_cat_test_001",
    )
    session = auth_client.session
    session["budget_filter_categories_hidden"] = [cf_category.slug]
    session.save()
    response = auth_client.get(reverse("budget:panel_transactions"))
    assert response.status_code == 200
    assert tx.display_name.encode() not in response.content


@pytest.mark.django_db
def test_panel_transactions_shows_all_when_no_hidden(auth_client, account, cf_category):
    """Aucune exclusion en session → toutes les transactions visibles."""
    from datetime import date

    tx = Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-42.00"),
        currency="CHF",
        amount_chf=Decimal("-42.00"),
        description_raw="VISIBLE TX NO FILTER",
        display_name="VISIBLE TX NO FILTER",
        import_hash="panel_no_filter_test_001",
    )
    response = auth_client.get(reverse("budget:panel_transactions"))
    assert response.status_code == 200
    assert tx.display_name.encode() in response.content


@pytest.mark.django_db
def test_panel_transactions_contains_category_filter(auth_client, cf_category):
    """Le panel transactions expose le composant filtre catégories dans le HTML."""
    r = auth_client.get(reverse("budget:panel_transactions"))
    assert r.status_code == 200
    assert b"categories-filter-details" in r.content


# =============================================================================
# budget_category_tx_fragment
# =============================================================================


@pytest.mark.django_db
def test_category_tx_fragment_respects_period(auth_client, account, cf_category):
    """Les transactions hors-période active ne doivent pas apparaître dans le fragment."""
    import calendar
    from datetime import date

    today = date.today()
    period_start = today.replace(day=1)
    period_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    # Tx dans la période courante
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=period_start,
        amount=Decimal("-10.00"),
        currency="CHF",
        amount_chf=Decimal("-10.00"),
        description_raw="TX DANS PERIODE",
        display_name="TX DANS PERIODE",
        import_hash="cat_frag_period_in_001",
    )
    # Tx hors-période : mois précédent
    prev_month = 12 if today.month == 1 else today.month - 1
    prev_year = today.year - 1 if today.month == 1 else today.year
    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date(prev_year, prev_month, 1),
        amount=Decimal("-99.00"),
        currency="CHF",
        amount_chf=Decimal("-99.00"),
        description_raw="TX HORS PERIODE",
        display_name="TX HORS PERIODE",
        import_hash="cat_frag_period_out_001",
    )
    session = auth_client.session
    session["budget_period_start"] = period_start.isoformat()
    session["budget_period_end"] = period_end.isoformat()
    session.save()

    r = auth_client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert r.status_code == 200
    assert b"TX DANS PERIODE" in r.content
    assert b"TX HORS PERIODE" not in r.content


@pytest.mark.django_db
def test_category_tx_fragment_requires_login(client, cf_category):
    r = client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


@pytest.mark.django_db
def test_category_tx_fragment_returns_200(auth_client, cf_category):
    r = auth_client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert r.status_code == 200


@pytest.mark.django_db
def test_category_tx_fragment_returns_inner_html_only(auth_client, cf_category):
    r = auth_client.get(reverse("budget:category_tx_fragment", args=[cf_category.slug]))
    assert b"<!DOCTYPE html>" not in r.content
    assert b"<html" not in r.content


@pytest.mark.django_db
def test_category_tx_fragment_returns_404_for_unknown_slug(auth_client):
    r = auth_client.get(
        reverse("budget:category_tx_fragment", args=["slug-qui-nexiste-pas"])
    )
    assert r.status_code == 404


@pytest.mark.django_db
def test_category_tx_fragment_shows_matching_transactions(
    auth_client, account, cf_category
):
    """Search q=MIGROS → transaction MIGROS présente dans le fragment."""
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-55.00"),
        currency="CHF",
        amount_chf=Decimal("-55.00"),
        description_raw="MIGROS GENEVE",
        display_name="MIGROS GENEVE",
        import_hash="cat_tx_frag_migros_001",
    )
    r = auth_client.get(
        reverse("budget:category_tx_fragment", args=[cf_category.slug]),
        {"q": "MIGROS"},
    )
    assert r.status_code == 200
    assert b"MIGROS" in r.content


@pytest.mark.django_db
def test_category_tx_fragment_search_excludes_non_matching(
    auth_client, account, cf_category
):
    """Search q=COOP → transaction MIGROS absente du fragment."""
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-20.00"),
        currency="CHF",
        amount_chf=Decimal("-20.00"),
        description_raw="MIGROS LAUSANNE",
        display_name="MIGROS LAUSANNE",
        import_hash="cat_tx_frag_migros_002",
    )
    r = auth_client.get(
        reverse("budget:category_tx_fragment", args=[cf_category.slug]),
        {"q": "COOP"},
    )
    assert r.status_code == 200
    assert b"MIGROS" not in r.content


@pytest.mark.django_db
def test_category_tx_fragment_idor_other_user_sees_no_data(
    other_client, account, cf_category
):
    """Autre user → 200 mais transactions du premier user invisibles."""
    from datetime import date

    Transaction.objects.create(
        account=account,
        category=cf_category,
        date=date.today().replace(day=1),
        amount=Decimal("-77.00"),
        currency="CHF",
        amount_chf=Decimal("-77.00"),
        description_raw="SECRET TX OTHER",
        display_name="SECRET TX OTHER",
        import_hash="cat_tx_frag_idor_001",
    )
    r = other_client.get(
        reverse("budget:category_tx_fragment", args=[cf_category.slug])
    )
    assert r.status_code == 200
    assert b"SECRET TX OTHER" not in r.content

"""
tests/budget/test_helpers.py

V2 — Tests unitaires sur les helpers privés :
  - _compute_category_cashflow_context : cœur du contexte category_detail
  - _resolve_bank_icon_map             : cache lru_cache sur scan FS
  - _cats_with_subcats                 : structure renvoyée par défaut
"""

import hashlib
from decimal import Decimal

import pytest

from accounts.models import Account, Bank
from budget.utils import _cats_with_subcats, _resolve_bank_icon_map
from budget.views.categories import _compute_category_cashflow_context
from transactions.models import BudgetTarget, Category, SubCategory, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="helpers@t.ch", password="p")


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="helpers-other@t.ch", password="p"
    )


@pytest.fixture
def bank(db):
    return Bank.objects.create(
        name="Helpers Bank",
        slug="helpers-bank",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def account(db, bank, user):
    acc = Account.objects.create(
        bank=bank, name="Helpers Account", account_type="checking", currency="CHF"
    )
    acc.members.add(user)
    return acc


@pytest.fixture
def account_other(db, bank, other_user):
    acc = Account.objects.create(
        bank=bank, name="Other Helpers Account", account_type="checking", currency="CHF"
    )
    acc.members.add(other_user)
    return acc


@pytest.fixture
def category(db):
    return Category.objects.create(
        name="Cat Helpers",
        slug="cat-helpers",
        colour_hex="#4ade80",
        order=99,
        is_system=False,
    )


def make_tx(account, category, amount="-10.00", is_ignored=False, seed=None):
    return Transaction.objects.create(
        account=account,
        category=category,
        date="2026-01-15",
        amount=Decimal(amount),
        currency="CHF",
        amount_chf=Decimal(amount),
        description_raw="helpers tx",
        display_name="helpers tx",
        is_ignored=is_ignored,
        import_hash=hashlib.sha256(
            f"helpers-{seed or amount}-{is_ignored}".encode()
        ).hexdigest(),
    )


def _make_request(rf, user, session_overrides=None):
    from importlib import import_module

    from django.conf import settings

    request = rf.get("/")
    request.user = user
    engine = import_module(settings.SESSION_ENGINE)
    request.session = engine.SessionStore()
    request.session["budget_period_start"] = "2026-01-01"
    request.session["budget_period_end"] = "2026-01-31"
    request.session["budget_period_mode"] = "1m"
    if session_overrides:
        request.session.update(session_overrides)
    return request


# =============================================================================
# _compute_category_cashflow_context
# =============================================================================


@pytest.mark.django_db
def test_compute_category_cashflow_returns_expected_keys(rf, user, category):
    req = _make_request(rf, user)
    ctx = _compute_category_cashflow_context(req, category)
    required = {
        "period_start",
        "period_end",
        "period_mode",
        "period_label",
        "period_months",
        "filter_account_ids",
        "base_qs",
        "txs_active",
        "total_amount",
        "subcat_list",
        "subcat_colors",
        "cat_color",
        "uncategorized_amount",
        "uncat_color",
        "sankey_data",
        "has_sankey",
        "tx_count",
        "cat_tab",
        "subcat_count",
        "budget_target",
        "target_amount",
        "target_pct",
        "on_track",
        "arc_fill_px",
    }
    missing = required - set(ctx.keys())
    assert not missing, f"Missing keys: {missing}"


@pytest.mark.django_db
def test_compute_category_cashflow_no_budget_target_returns_none(rf, user, category):
    req = _make_request(rf, user)
    ctx = _compute_category_cashflow_context(req, category)
    assert ctx["budget_target"] is None
    assert ctx["target_amount"] is None
    assert ctx["target_pct"] is None
    assert ctx["on_track"] is None


@pytest.mark.django_db
def test_compute_category_cashflow_ignored_txs_excluded_from_total(
    rf, user, account, category
):
    make_tx(account, category, amount="-100.00", is_ignored=False, seed="active")
    make_tx(account, category, amount="-50.00", is_ignored=True, seed="ignored")
    req = _make_request(rf, user)
    ctx = _compute_category_cashflow_context(req, category)
    assert abs(ctx["total_amount"]) == Decimal("100.00")
    assert ctx["tx_count"] == 1


@pytest.mark.django_db
def test_compute_category_cashflow_scoped_to_user(
    rf, user, other_user, account, account_other, category
):
    """Les transactions d'un autre user ne doivent pas être comptées."""
    make_tx(account, category, amount="-30.00", seed="mine")
    make_tx(account_other, category, amount="-500.00", seed="theirs")
    req = _make_request(rf, user)
    ctx = _compute_category_cashflow_context(req, category)
    assert abs(ctx["total_amount"]) == Decimal("30.00")
    # Pas de leak des données de l'autre user dans tx_count
    assert ctx["tx_count"] == 1


@pytest.mark.django_db
def test_compute_category_cashflow_with_budget_target_computes_pct(
    rf, user, account, category
):
    BudgetTarget.objects.create(category=category, amount=Decimal("200"))
    make_tx(account, category, amount="-50.00", seed="t")
    req = _make_request(rf, user)
    ctx = _compute_category_cashflow_context(req, category)
    assert ctx["budget_target"] is not None
    assert ctx["target_amount"] == Decimal("200")
    assert ctx["target_pct"] == 25  # 50/200 = 25%
    assert ctx["on_track"] is True


# =============================================================================
# _resolve_bank_icon_map — cache lru_cache + scan FS
# =============================================================================


def test_resolve_bank_icon_map_returns_dict():
    result = _resolve_bank_icon_map()
    assert isinstance(result, dict)


def test_resolve_bank_icon_map_cached():
    """lru_cache → 2 appels = même objet (référence identique)."""
    a = _resolve_bank_icon_map()
    b = _resolve_bank_icon_map()
    assert a is b  # même référence en mémoire


# =============================================================================
# _cats_with_subcats — structure
# =============================================================================


@pytest.mark.django_db
def test_cats_with_subcats_returns_tuple(category):
    result = _cats_with_subcats()
    assert isinstance(result, tuple)
    assert len(result) == 2


@pytest.mark.django_db
def test_cats_with_subcats_includes_category(category):
    """_cats_with_subcats doit inclure la catégorie active."""
    SubCategory.objects.create(
        category=category, name="Sub Helpers", slug="sub-helpers", is_system=False
    )
    cats_only, cats_with_subs = _cats_with_subcats()
    cat_ids = [c.id for c in cats_only]
    assert category.id in cat_ids
    # cats_with_subs : iter[(cat, list_of_subs)] — la catégorie doit s'y trouver
    cat_ids_with = [c.id for c, _ in cats_with_subs]
    assert category.id in cat_ids_with

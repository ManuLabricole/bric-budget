"""
tests/transactions/test_internal_transfer.py

Tests : sync_internal_transfer() + propagation aux 3 points de catégorisation.

Règle métier : catégorie "Virements" → is_ignored=True + is_internal_transfer=True.
Sans propagation aux 3 endroits (vue, import, apply_rules), les virements faussent les KPIs.
"""

import hashlib

import pytest
from django.test import Client
from django.urls import reverse

from transactions.management.commands.apply_rules import Command as ApplyRulesCommand
from transactions.models import CategorizationRule, Category, Transaction
from transactions.services import sync_internal_transfer

# =============================================================================
# Fixtures communes
# =============================================================================


@pytest.fixture
def cat_virements(db):
    return Category.objects.create(
        name="Virements",
        slug="virements",
        colour_hex="#5abdc5",
        order=99,
        is_system=True,
    )


@pytest.fixture
def cat_alim(db):
    return Category.objects.create(
        name="Alimentation",
        slug="alimentation_test",
        colour_hex="#aaa",
        order=50,
        is_system=False,
    )


@pytest.fixture
def account(db):
    from accounts.models import Account, Bank

    bank = Bank.objects.create(
        name="Test Bank",
        slug="test-bank-intl",
        country="CH",
        default_currency="CHF",
    )
    return Account.objects.create(
        bank=bank, name="Test Account", account_type="checking", currency="CHF"
    )


def make_tx(account, display_name, category=None, seed=None):
    return Transaction.objects.create(
        account=account,
        date="2026-01-15",
        amount=-10,
        currency="CHF",
        amount_chf=-10,
        description_raw=display_name,
        display_name=display_name,
        category=category,
        import_hash=hashlib.sha256(
            f"intl-test:{seed or display_name}".encode()
        ).hexdigest(),
    )


# =============================================================================
# A. sync_internal_transfer() — unité
# =============================================================================


@pytest.mark.django_db
def test_sync_internal_virements_sets_both_flags_true(cat_virements, account):
    tx = make_tx(account, "VIREMENT CIC", category=cat_virements)
    tx.is_internal_transfer = False
    tx.is_ignored = False
    changed = sync_internal_transfer(tx)
    assert tx.is_internal_transfer is True
    assert tx.is_ignored is True
    assert "is_internal_transfer" in changed
    assert "is_ignored" in changed


@pytest.mark.django_db
def test_sync_internal_other_category_sets_both_flags_false(cat_alim, account):
    tx = make_tx(account, "MIGROS", category=cat_alim)
    tx.is_internal_transfer = True
    tx.is_ignored = True
    changed = sync_internal_transfer(tx)
    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False
    assert "is_internal_transfer" in changed
    assert "is_ignored" in changed


@pytest.mark.django_db
def test_sync_internal_already_up_to_date_returns_empty(cat_virements, account):
    tx = make_tx(account, "VIREMENT YUH→CIC", category=cat_virements)
    tx.is_internal_transfer = True
    tx.is_ignored = True
    assert sync_internal_transfer(tx) == []


@pytest.mark.django_db
def test_sync_internal_no_category_is_not_internal(account):
    tx = make_tx(account, "INCONNU")
    tx.is_internal_transfer = False
    tx.is_ignored = False
    assert sync_internal_transfer(tx) == []
    assert tx.is_internal_transfer is False


# =============================================================================
# B. budget_categorize_transaction — vue HTTP
# =============================================================================


@pytest.fixture
def test_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="test@bricbudget.ch", password="pass"
    )


@pytest.fixture
def auth_client(test_user):
    c = Client()
    c.force_login(test_user)
    return c


@pytest.mark.django_db
def test_categorize_to_virements_sets_internal_flags(
    auth_client, test_user, cat_virements, account
):
    account.members.add(test_user)
    tx = make_tx(account, "TRANSFERT EMMANUEL BARRIOL", seed="t1")
    auth_client.post(
        reverse("budget:categorize"), {"tx_id": tx.id, "category_id": cat_virements.id}
    )
    tx.refresh_from_db()
    assert tx.is_internal_transfer is True
    assert tx.is_ignored is True
    assert tx.categorization_source == "manual"


@pytest.mark.django_db
def test_categorize_away_from_virements_resets_flags(
    auth_client, test_user, cat_virements, cat_alim, account
):
    account.members.add(test_user)
    tx = make_tx(account, "TRANSFERT", category=cat_virements, seed="t2")
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])
    auth_client.post(
        reverse("budget:categorize"), {"tx_id": tx.id, "category_id": cat_alim.id}
    )
    tx.refresh_from_db()
    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False


@pytest.mark.django_db
def test_manual_toggle_ignore_does_not_change_internal_transfer_flag(
    auth_client, test_user, cat_virements, account
):
    """toggle_ignore NE modifie PAS is_internal_transfer — c'est un booléen catégorie."""
    account.members.add(test_user)
    tx = make_tx(account, "VIREMENT INTERNE", category=cat_virements, seed="t3")
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])
    auth_client.post(reverse("budget:toggle_ignore", args=[tx.id]), {"source": "list"})
    tx.refresh_from_db()
    assert tx.is_ignored is False
    assert tx.is_internal_transfer is True  # inchangé


# =============================================================================
# C. ImportService — import CSV
# =============================================================================


@pytest.mark.django_db
def test_import_virements_category_sets_ignored_at_import(cat_virements, account):
    from transactions.services import ImportService

    rule = CategorizationRule.objects.create(
        keyword="VIREMENT",
        category=cat_virements,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx_obj = ImportService()._build_transaction(
        {
            "display_name": "VIREMENT YUH CIC",
            "description_raw": "VIREMENT YUH CIC",
            "merchant_name": "VIREMENT YUH CIC",
            "amount": -500.0,
            "currency": "CHF",
            "date": "2026-01-15",
            "time": None,
            "import_hash": hashlib.sha256(b"import-test-virement").hexdigest(),
            "card_last_four": None,
            "balance_after": None,
        },
        account=account,
        cards_by_last_four={},
        rules=[rule],
        default_income_category=None,
        default_unknown_category=None,
    )
    assert tx_obj.is_internal_transfer is True
    assert tx_obj.is_ignored is True
    assert tx_obj.category == cat_virements


@pytest.mark.django_db
def test_import_non_virements_category_does_not_set_ignored(cat_alim, account):
    from transactions.services import ImportService

    rule = CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx_obj = ImportService()._build_transaction(
        {
            "display_name": "MIGROS LAUSANNE",
            "description_raw": "MIGROS LAUSANNE",
            "merchant_name": "MIGROS LAUSANNE",
            "amount": -25.0,
            "currency": "CHF",
            "date": "2026-01-15",
            "time": None,
            "import_hash": hashlib.sha256(b"import-test-migros").hexdigest(),
            "card_last_four": None,
            "balance_after": None,
        },
        account=account,
        cards_by_last_four={},
        rules=[rule],
        default_income_category=None,
        default_unknown_category=None,
    )
    assert tx_obj.is_internal_transfer is False
    assert tx_obj.is_ignored is False


# =============================================================================
# D. apply_rules command
# =============================================================================


def run_apply_rules():
    from io import StringIO

    cmd = ApplyRulesCommand()
    cmd.stdout = StringIO()  # type: ignore[assignment]
    cmd.handle(dry_run=False, limit=None, reset=False)


@pytest.mark.django_db
def test_apply_rules_virements_rule_sets_ignored(cat_virements, account):
    CategorizationRule.objects.create(
        keyword="VIREMENT",
        category=cat_virements,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_tx(account, "VIREMENT MENSUEL", seed="ar1")
    run_apply_rules()
    tx.refresh_from_db()
    assert tx.is_ignored is True
    assert tx.is_internal_transfer is True
    assert tx.categorization_source == "rule"


@pytest.mark.django_db
def test_apply_rules_non_virements_rule_does_not_set_ignored(cat_alim, account):
    CategorizationRule.objects.create(
        keyword="COOP",
        category=cat_alim,
        target_field="display_name",
        priority=1,
        is_active=True,
    )
    tx = make_tx(account, "COOP GENEVE", seed="ar2")
    run_apply_rules()
    tx.refresh_from_db()
    assert tx.is_ignored is False
    assert tx.is_internal_transfer is False
    assert tx.category == cat_alim


@pytest.mark.django_db
def test_apply_rules_changing_from_virements_to_other_resets_flags(
    cat_virements, cat_alim, account
):
    CategorizationRule.objects.create(
        keyword="MIGROS",
        category=cat_alim,
        target_field="display_name",
        priority=5,
        is_active=True,
    )
    tx = make_tx(account, "MIGROS LAUSANNE", seed="ar3")
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])
    run_apply_rules()
    tx.refresh_from_db()
    assert tx.is_internal_transfer is False
    assert tx.is_ignored is False
    assert tx.category == cat_alim


# =============================================================================
# E. Template rendering — badge "Classifiée comme mouvement interne"
# =============================================================================


@pytest.mark.django_db
def test_panel_tx_detail_shows_badge_when_internal_transfer(cat_virements, account):
    from django.template.loader import render_to_string

    tx = make_tx(account, "VIREMENT YUH → CIC", category=cat_virements)
    tx.is_internal_transfer = True
    tx.is_ignored = True
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])
    html = render_to_string(
        "budget/_panel_tx_detail.html",
        {"tx": tx, "bank_icon_url": "", "close_on_back": False, "source": "detail"},
    )
    assert "Classifiée comme mouvement interne" in html


@pytest.mark.django_db
def test_panel_tx_detail_no_badge_when_not_internal_transfer(cat_alim, account):
    from django.template.loader import render_to_string

    tx = make_tx(account, "MIGROS LAUSANNE", category=cat_alim)
    tx.is_internal_transfer = False
    tx.is_ignored = False
    tx.save(update_fields=["is_internal_transfer", "is_ignored"])
    html = render_to_string(
        "budget/_panel_tx_detail.html",
        {"tx": tx, "bank_icon_url": "", "close_on_back": False, "source": "detail"},
    )
    assert "Classifiée comme mouvement interne" not in html


# =============================================================================
# F. Toggle ignore depuis panneau détail contexte category
# =============================================================================


@pytest.mark.django_db
def test_toggle_ignore_from_detail_close_on_back_returns_oob_and_cashflow_signal(
    auth_client, test_user, cat_alim, account
):
    account.members.add(test_user)
    tx = make_tx(account, "MIGROS", category=cat_alim, seed="oob1")
    tx.is_ignored = False
    tx.save(update_fields=["is_ignored"])
    response = auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "detail", "close_on_back": "true"},
        HTTP_HX_CURRENT_URL="/budget/categorie/alimentation/",
    )
    assert response.status_code == 200
    assert not response.has_header("HX-Redirect")
    content = response.content.decode()
    assert 'hx-swap-oob="outerHTML"' in content
    assert "data-cashflow-refresh" in content


@pytest.mark.django_db
def test_toggle_ignore_from_detail_no_oob_when_not_close_on_back(
    auth_client, test_user, cat_alim, account
):
    account.members.add(test_user)
    tx = make_tx(account, "MIGROS", category=cat_alim, seed="oob2")
    response = auth_client.post(
        reverse("budget:toggle_ignore", args=[tx.id]),
        {"source": "detail", "close_on_back": "false"},
    )
    assert response.status_code == 200
    assert "hx-swap-oob" not in response.content.decode()

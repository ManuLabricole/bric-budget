"""
tests/imports/test_chart_date.py

Tests : le graphique d'import utilise Transaction.date (pas ImportLog.imported_at).

Fix D-010 : chart_data.logs source = Transaction.date réelle, pas date d'import.
Un import bulk de 4 000 tx créait un spike géant sur la date d'import sinon.
"""

import datetime

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from transactions.models import ImportLog, Transaction

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@chart-test.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@chart-test.ch", password="pass"
    )


@pytest.fixture
def bank(db):
    from accounts.models import Institution

    return Institution.objects.create(
        name="TestBank",
        slug="testbank",
        country="CH",
        default_currency="CHF",
        is_active=True,
    )


@pytest.fixture
def account_a(db, bank, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=bank,
        name="Compte A",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_active=True,
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def account_b(db, bank, user_b):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=bank,
        name="Compte B",
        account_type=Account.AccountType.CHECKING,
        currency="CHF",
        is_active=True,
    )
    acc.members.add(user_b)
    return acc


@pytest.fixture
def category(db):
    from transactions.models import Category

    return Category.objects.create(
        name="Test",
        slug="test",
        colour_hex="#000000",
        order=1,
        is_system=False,
        is_active=True,
    )


_tx_counter = 0


def make_tx(account, category, date, amount="-10.00", is_ignored=False):
    from decimal import Decimal

    global _tx_counter
    _tx_counter += 1
    return Transaction.objects.create(
        account=account,
        category=category,
        date=date,
        amount=Decimal(amount),
        amount_chf=Decimal(amount),
        currency="CHF",
        description_raw="test tx",
        import_hash=f"test-hash-{_tx_counter:06d}",
        is_ignored=is_ignored,
    )


def make_import_log(account, imported_at, count_created=5, filename="test.csv"):
    user = account.members.first()
    return ImportLog.objects.create(
        account=account,
        imported_by=user,
        filename=filename,
        file_hash=f"hash-{filename}-{imported_at}",
        imported_at=imported_at,
        status=ImportLog.Status.SUCCESS,
        count_created=count_created,
        count_skipped=0,
        count_errors=0,
    )


# =============================================================================
# Tests
# =============================================================================


def test_chart_data_uses_transaction_date(db, user_a, account_a, category):
    """Les barres reflètent la date réelle des transactions, pas la date d'import."""
    tx_date = datetime.date.today() - datetime.timedelta(days=90)
    make_tx(account_a, category, tx_date)
    make_tx(account_a, category, tx_date)

    client = Client()
    client.force_login(user_a)
    response = client.get(reverse("imports:upload"))

    assert response.status_code == 200
    chart_data = response.context["chart_data"]
    log_dates = [log["date"] for log in chart_data["logs"]]
    assert tx_date.strftime("%Y-%m-%d") in log_dates
    assert datetime.date.today().strftime("%Y-%m-%d") not in log_dates


def test_chart_data_import_markers_present(db, user_a, account_a, category):
    """import_markers contient les métadonnées de chaque import."""
    import_date = timezone.now()
    make_import_log(account_a, import_date, count_created=42, filename="yuh.csv")

    client = Client()
    client.force_login(user_a)
    response = client.get(reverse("imports:upload"))

    assert response.status_code == 200
    markers = response.context["chart_data"]["import_markers"]
    assert len(markers) == 1
    assert markers[0]["filename"] == "yuh.csv"
    assert markers[0]["total"] == 42
    assert markers[0]["bank"] == "TestBank"
    assert markers[0]["date"] == timezone.localtime(import_date).strftime("%Y-%m-%d")


def test_chart_data_idor_isolation(db, user_a, account_a, user_b, account_b, category):
    """User A ne voit pas les transactions de User B dans chart_data."""
    tx_date = datetime.date.today() - datetime.timedelta(days=10)
    make_tx(account_a, category, tx_date, amount="-10.00")
    make_tx(account_b, category, tx_date, amount="-999.00")

    client = Client()
    client.force_login(user_a)
    response = client.get(reverse("imports:upload"))

    assert response.status_code == 200
    total_visible = sum(
        log["created"] for log in response.context["chart_data"]["logs"]
    )
    assert total_visible == 1


def test_chart_data_excludes_ignored_transactions(db, user_a, account_a, category):
    """Les transactions is_ignored=True n'apparaissent pas dans chart_data."""
    tx_date = datetime.date.today() - datetime.timedelta(days=5)
    make_tx(account_a, category, tx_date, is_ignored=False)
    make_tx(account_a, category, tx_date, is_ignored=True)

    client = Client()
    client.force_login(user_a)
    response = client.get(reverse("imports:upload"))

    assert response.status_code == 200
    total_visible = sum(
        log["created"] for log in response.context["chart_data"]["logs"]
    )
    assert total_visible == 1

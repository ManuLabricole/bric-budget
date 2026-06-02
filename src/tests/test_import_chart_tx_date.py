"""
tests/test_import_chart_tx_date.py

Tests : le graphique d'import utilise Transaction.date (pas ImportLog.imported_at).

Problème résolu :
    L'import initial bulk (ex: 4 000 tx Yuh) importé le 2026-01-15 créait un spike
    géant sur la date d'import, masquant toute l'activité réelle.
    Fix D-010 : chart_data.logs source = Transaction.date réelle.

Scénarios :
    1. chart_data.logs contient les dates réelles des transactions (pas la date d'import)
    2. chart_data.import_markers contient la date d'import, filename, total, bank
    3. IDOR : un user ne voit que ses propres transactions dans chart_data
    4. Les transactions is_ignored=True sont exclues du graphique
"""

import datetime

import pytest
from django.test import Client
from django.urls import reverse

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
    from accounts.models import Bank

    return Bank.objects.create(
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
        bank=bank,
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
        bank=bank,
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
        # import_hash est UNIQUE — on génère un hash distinct par transaction de test.
        import_hash=f"test-hash-{_tx_counter:06d}",
        is_ignored=is_ignored,
    )


def make_import_log(account, imported_at, count_created=5, filename="test.csv"):
    # imported_by = premier membre du compte (NOT NULL en DB)
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
    """Les barres du graphique reflètent la date réelle des transactions."""
    # Import fait aujourd'hui, mais les transactions datent de 3 mois avant
    tx_date = datetime.date.today() - datetime.timedelta(days=90)
    make_tx(account_a, category, tx_date)
    make_tx(account_a, category, tx_date)

    client = Client()
    client.force_login(user_a)
    response = client.get(reverse("imports:upload"))

    assert response.status_code == 200
    chart_data = response.context["chart_data"]

    # Les logs doivent contenir la date réelle de la transaction
    log_dates = [log["date"] for log in chart_data["logs"]]
    assert tx_date.strftime("%Y-%m-%d") in log_dates

    # Pas la date d'import (aujourd'hui) comme date de barre
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    assert today_str not in log_dates


def test_chart_data_import_markers_present(db, user_a, account_a, category):
    """import_markers contient les métadonnées de chaque import."""
    import_date = datetime.datetime.now()
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
    assert markers[0]["date"] == import_date.strftime("%Y-%m-%d")


def test_chart_data_idor_isolation(db, user_a, account_a, user_b, account_b, category):
    """User A ne voit pas les transactions de User B dans chart_data."""
    tx_date = datetime.date.today() - datetime.timedelta(days=10)
    make_tx(account_a, category, tx_date, amount="-10.00")
    make_tx(
        account_b, category, tx_date, amount="-999.00"
    )  # user B — ne doit pas apparaître

    client = Client()
    client.force_login(user_a)
    response = client.get(reverse("imports:upload"))

    assert response.status_code == 200
    logs = response.context["chart_data"]["logs"]

    # Total tx visibles pour user A : 1 seule (pas celle de B)
    total_visible = sum(log["created"] for log in logs)
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
    logs = response.context["chart_data"]["logs"]

    total_visible = sum(log["created"] for log in logs)
    assert total_visible == 1  # seule la transaction non-ignorée

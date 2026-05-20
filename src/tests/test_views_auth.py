"""
tests/test_views_auth.py

Tests : toutes les vues protégées par @login_required redirigent vers /login/
        quand un utilisateur non connecté tente d'y accéder.

Pourquoi ces tests sont importants :
    Chaque @login_required sur une vue est un contrat. Si quelqu'un retire le
    décorateur par inadvertance, ces tests cassent immédiatement. Sans eux,
    la régression peut passer inaperçue jusqu'en prod.

Pattern utilisé :
    - client Django non connecté (pas de force_login)
    - Vérification status 302 + "Location" contient "/login/"
    - Un test par URL "famille" (on ne teste pas les 40 vues, mais 1 par app)
"""

import pytest
from django.urls import reverse

# =============================================================================
# Fixtures minimales — juste assez pour construire les URLs sans 404 de routing
# =============================================================================


@pytest.fixture
def some_category(db):
    from transactions.models import Category

    return Category.objects.create(
        name="Auth test cat",
        slug="auth-test-cat",
        colour_hex="#aaa",
        order=99,
        is_system=False,
    )


@pytest.fixture
def some_rule(db, some_category):
    from transactions.models import CategorizationRule

    return CategorizationRule.objects.create(
        keyword="AUTHTEST",
        category=some_category,
        target_field="display_name",
        priority=1,
        is_active=True,
    )


@pytest.fixture
def some_import_log(db, some_category):
    """ImportLog minimal pour tester les URLs avec pk."""
    from django.contrib.auth import get_user_model

    from accounts.models import Account, Bank
    from transactions.models import ImportLog

    User = get_user_model()
    user = User.objects.create_user(email="importlog@auth.ch", password="pass")
    bank = Bank.objects.create(
        name="Auth Bank", slug="auth-bank", country="CH", default_currency="CHF"
    )
    acc = Account.objects.create(
        bank=bank, name="Auth Account", account_type="checking", currency="CHF"
    )
    acc.members.add(user)
    return ImportLog.objects.create(
        account=acc,
        imported_by=user,
        filename="test.csv",
        file_hash="a" * 64,
        status="success",
    )


# =============================================================================
# budget/ — vues sans paramètre de routing
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
# budget/ — vues avec paramètre slug ou pk
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
# imports/ — vues protégées
# =============================================================================


@pytest.mark.django_db
def test_import_upload_requires_login(client):
    response = client.get(reverse("imports:upload"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_import_log_detail_requires_login(client, some_import_log):
    response = client.get(reverse("imports:log_detail", args=[some_import_log.pk]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_import_log_delete_requires_login(client, some_import_log):
    response = client.post(reverse("imports:log_delete", args=[some_import_log.pk]))
    assert response.status_code == 302
    assert "/login/" in response["Location"]

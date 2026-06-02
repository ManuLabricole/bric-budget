"""
tests/imports/test_views.py

Tests des vues imports/ :
  - Auth : upload, log_detail, log_delete redirigent en 302 pour user non connecté
"""

import pytest
from django.urls import reverse


@pytest.fixture
def some_import_log(db):
    from django.contrib.auth import get_user_model

    from accounts.models import Account, Bank
    from transactions.models import ImportLog

    user = get_user_model().objects.create_user(
        email="importlog@auth.ch", password="pass"
    )
    bank = Bank.objects.create(
        name="Auth Bank", slug="auth-bank-imports", country="CH", default_currency="CHF"
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

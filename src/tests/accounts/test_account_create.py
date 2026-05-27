import pytest
from django.urls import reverse

from accounts.models import Account, CheckingAccount


@pytest.fixture
def bank(db):
    from accounts.models import Bank

    return Bank.objects.create(name="TestBank", slug="testbank", country="CH")


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(email="u@test.com", password="pw")


@pytest.mark.django_db
def test_account_new_get_returns_200(client, user):
    client.force_login(user)
    response = client.get(reverse("accounts:account_new"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_account_new_requires_login(client):
    response = client.get(reverse("accounts:account_new"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_account_new_post_creates_checking_account(client, user, bank):
    client.force_login(user)
    response = client.post(
        reverse("accounts:account_new"),
        {
            "bank_slug": "testbank",
            "account_name": "Mon Yuh",
            "account_type": "checking",
            "iban": "CH5604835012345678009",
            "bic": "YUHCCH22",
            "currency": "CHF",
        },
    )
    assert response.status_code == 302
    assert Account.objects.filter(name="Mon Yuh").exists()
    assert CheckingAccount.objects.filter(account__name="Mon Yuh").exists()


@pytest.mark.django_db
def test_account_new_post_adds_user_as_member(client, user, bank):
    client.force_login(user)
    client.post(
        reverse("accounts:account_new"),
        {
            "bank_slug": "testbank",
            "account_name": "Mon Yuh",
            "account_type": "checking",
            "iban": "CH5604835012345678009",
            "bic": "",
            "currency": "CHF",
        },
    )
    account = Account.objects.get(name="Mon Yuh")
    assert user in account.members.all()


@pytest.mark.django_db
def test_account_new_post_account_visible_via_for_user(client, user, bank):
    """for_user() doit retrouver le compte après création — valide le members.add."""
    client.force_login(user)
    client.post(
        reverse("accounts:account_new"),
        {
            "bank_slug": "testbank",
            "account_name": "Mon Yuh",
            "account_type": "checking",
            "iban": "CH5604835012345678009",
            "bic": "",
            "currency": "CHF",
        },
    )
    assert Account.objects.for_user(user).filter(name="Mon Yuh").exists()


@pytest.mark.django_db
def test_account_new_post_missing_name_returns_error(client, user, bank):
    client.force_login(user)
    response = client.post(
        reverse("accounts:account_new"),
        {
            "bank_slug": "testbank",
            "account_name": "",
            "account_type": "checking",
            "iban": "CH5604835012345678009",
            "currency": "CHF",
        },
    )
    assert response.status_code == 200
    assert "obligatoire" in response.content.decode()


@pytest.mark.django_db
def test_account_new_post_unknown_bank_returns_error(client, user):
    client.force_login(user)
    response = client.post(
        reverse("accounts:account_new"),
        {
            "bank_slug": "banque-inconnue",
            "account_name": "Mon compte",
            "account_type": "checking",
            "iban": "CH5604835012345678009",
            "currency": "CHF",
        },
    )
    assert response.status_code == 200
    assert "introuvable" in response.content.decode()

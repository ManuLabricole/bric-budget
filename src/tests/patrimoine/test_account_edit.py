"""
tests/patrimoine/test_account_edit.py — édition & archivage compte (#292), couche HTTP.

Vérifie : auth + garde HX · GET carte → formulaire prérempli · POST update persiste
(nom/devise/champs type) · IBAN d'un savings non écrasé · CHF forcé pour la prévoyance
· erreurs re-rendues en 422 sans muter la DB · IDOR (compte d'autrui → 404) · archive
= soft-delete + HX-Redirect, et le compte sort des listes (404 ensuite).
La logique de mutation est testée dans tests/accounts/test_update_account_service.py.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertTemplateUsed,
)

from patrimoine.views.account_detail import back_url_for
from tests.factories import (
    AccountFactory,
    CheckingAccountFactory,
    SavingsAccountFactory,
    UserFactory,
)

_HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def checking_account(user):
    account = AccountFactory(
        members=[user],
        account_type="checking",
        currency="CHF",
        iban="CH5604835012345678009",
        name="Compte courant",
    )
    CheckingAccountFactory(account=account, bic="BCVLCH2L")
    return account


def _edit_url(account):
    return reverse("patrimoine:account_edit_form", args=[account.pk])


def _update_url(account):
    return reverse("patrimoine:account_update", args=[account.pk])


def _archive_url(account):
    return reverse("patrimoine:account_archive", args=[account.pk])


# =============================================================================
# GET account_edit_form — carte → formulaire
# =============================================================================


def test_edit_form_requires_login(client, checking_account):
    resp = client.get(_edit_url(checking_account), **_HX)
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


def test_edit_form_direct_nav_redirects_to_detail(client_logged, checking_account):
    # Sans header HX : endpoint de swap → on renvoie vers la page compte, pas un partial nu.
    resp = client_logged.get(_edit_url(checking_account))
    assert resp.status_code == 302
    assert (
        reverse("patrimoine:account_detail", args=[checking_account.pk])
        in resp["Location"]
    )


def test_edit_form_renders_prefilled_fragment(client_logged, checking_account):
    resp = client_logged.get(_edit_url(checking_account), **_HX)
    assert resp.status_code == 200
    assertTemplateUsed(resp, "patrimoine/partials/_account_detail_panel.html")
    assertNotContains(resp, "<!DOCTYPE html>")  # fragment, pas la page
    assertContains(resp, 'value="Compte courant"')  # nom prérempli
    assertContains(resp, "CH5604835012345678009")  # IBAN prérempli
    assertContains(resp, 'name="currency"')  # devise éditable (checking)
    assertContains(resp, _archive_url(checking_account))  # zone d'archivage présente


def test_edit_form_idor_other_user_404(client, checking_account):
    intruder = UserFactory()
    client.force_login(intruder)
    resp = client.get(_edit_url(checking_account), **_HX)
    assert resp.status_code == 404


# =============================================================================
# POST account_update
# =============================================================================


def test_update_persists_and_returns_read_card(client_logged, checking_account):
    resp = client_logged.post(
        _update_url(checking_account),
        {
            "name": "Compte renommé",
            "currency": "EUR",
            "iban": "CH5604835012345678009",
            "bic": "BCVLCH2L",
            "contract_number": "",
        },
        **_HX,
    )
    assert resp.status_code == 200
    # Carte re-rendue en LECTURE → bon partial + bouton Modifier, sans champ de saisie.
    assertTemplateUsed(resp, "patrimoine/partials/_account_detail_panel.html")
    assertContains(resp, _edit_url(checking_account))
    assertNotContains(resp, 'name="currency"')  # plus le formulaire d'édition
    checking_account.refresh_from_db()
    assert checking_account.name == "Compte renommé"
    assert checking_account.currency == "EUR"


def test_update_direct_nav_redirects_to_detail(client_logged, checking_account):
    # Garde HX de account_update : un POST hors HTMX ne mute pas, il redirige.
    resp = client_logged.post(
        _update_url(checking_account),
        {
            "name": "X",
            "currency": "CHF",
            "iban": "CH5604835012345678009",
            "contract_number": "",
        },
    )
    assert resp.status_code == 302
    assert (
        reverse("patrimoine:account_detail", args=[checking_account.pk])
        in resp["Location"]
    )
    checking_account.refresh_from_db()
    assert checking_account.name == "Compte courant"  # inchangé


def test_update_checking_can_clear_iban_when_contract_present(
    client_logged, checking_account
):
    # IBAN vidé (champ checking présent mais vide) → None, autorisé car contrat fourni.
    # Discrimine la branche `type_fields.get("iban") or None`.
    resp = client_logged.post(
        _update_url(checking_account),
        {
            "name": "Compte courant",
            "currency": "CHF",
            "iban": "",
            "contract_number": "C-999",
        },
        **_HX,
    )
    assert resp.status_code == 200
    checking_account.refresh_from_db()
    assert checking_account.iban is None
    assert checking_account.contract_number == "C-999"


def test_update_savings_does_not_wipe_iban(user, client_logged):
    account = AccountFactory(
        members=[user],
        account_type="savings",
        currency="CHF",
        iban="CH5604835012345678009",
        name="Livret",
    )
    SavingsAccountFactory(account=account, interest_rate=Decimal("1.00"))

    resp = client_logged.post(
        _update_url(account),
        {
            "name": "Livret V2",
            "currency": "CHF",
            "interest_rate": "2.5",
            "contract_number": "",
        },
        **_HX,
    )

    assert resp.status_code == 200
    account.refresh_from_db()
    assert account.iban == "CH5604835012345678009"  # non effacé par omission
    assert account.name == "Livret V2"
    assert account.savings_account.interest_rate == Decimal("2.5")


def test_update_pension_forces_chf(user, client_logged):
    account = AccountFactory(
        members=[user],
        account_type="pension_3a",
        currency="CHF",
        iban=None,
        contract_number="3A-123",
    )
    resp = client_logged.post(
        _update_url(account),
        {"name": "3e pilier", "currency": "EUR", "contract_number": "3A-123"},
        **_HX,
    )
    assert resp.status_code == 200
    account.refresh_from_db()
    assert account.currency == "CHF"  # EUR ignoré, CHF forcé


def test_update_empty_name_rerenders_422_no_change(client_logged, checking_account):
    resp = client_logged.post(
        _update_url(checking_account),
        {
            "name": "",
            "currency": "CHF",
            "iban": "CH5604835012345678009",
            "contract_number": "",
        },
        **_HX,
    )
    assert resp.status_code == 422
    assertContains(resp, "obligatoire", status_code=422)
    checking_account.refresh_from_db()
    assert checking_account.name == "Compte courant"  # inchangé


def test_update_duplicate_iban_rerenders_422_no_change(
    user, client_logged, checking_account
):
    other = AccountFactory(
        members=[user],
        account_type="checking",
        currency="CHF",
        iban="CH9300762011623852957",
        name="Autre",
    )
    CheckingAccountFactory(account=other)

    resp = client_logged.post(
        _update_url(checking_account),
        {
            "name": "Compte courant",
            "currency": "CHF",
            "iban": "CH9300762011623852957",  # déjà pris par `other`
            "contract_number": "",
        },
        **_HX,
    )
    assert resp.status_code == 422
    assertContains(resp, "existe déjà", status_code=422)
    checking_account.refresh_from_db()
    assert checking_account.iban == "CH5604835012345678009"  # inchangé


def test_update_idor_other_user_404(client, checking_account):
    intruder = UserFactory()
    client.force_login(intruder)
    resp = client.post(
        _update_url(checking_account),
        {
            "name": "Hacked",
            "currency": "CHF",
            "iban": "CH5604835012345678009",
            "contract_number": "",
        },
        **_HX,
    )
    assert resp.status_code == 404
    checking_account.refresh_from_db()
    assert checking_account.name == "Compte courant"  # intact


# =============================================================================
# POST account_archive — soft-delete
# =============================================================================


def test_archive_requires_login(client, checking_account):
    resp = client.post(_archive_url(checking_account), **_HX)
    assert resp.status_code == 302
    assert "/login" in resp["Location"]
    checking_account.refresh_from_db()
    assert checking_account.is_active is True  # pas de soft-delete sans auth


def test_archive_direct_nav_does_not_delete(client_logged, checking_account):
    # Garde HX : un POST hors HTMX redirige sans archiver (pas de suppression hors flux).
    resp = client_logged.post(_archive_url(checking_account))
    assert resp.status_code == 302
    checking_account.refresh_from_db()
    assert checking_account.is_active is True


def test_archive_soft_deletes_and_redirects(client_logged, checking_account):
    resp = client_logged.post(_archive_url(checking_account), **_HX)
    assert resp.status_code == 204
    # Cible du renvoi discriminée (back_url_for : classe d'actifs du compte).
    assert resp["HX-Redirect"] == back_url_for(checking_account)
    checking_account.refresh_from_db()
    assert checking_account.is_active is False
    # Le compte archivé n'est plus accessible en lecture (sort de for_user actif).
    detail = client_logged.get(
        reverse("patrimoine:account_detail", args=[checking_account.pk])
    )
    assert detail.status_code == 404


def test_archive_idor_other_user_404(client, checking_account):
    intruder = UserFactory()
    client.force_login(intruder)
    resp = client.post(_archive_url(checking_account), **_HX)
    assert resp.status_code == 404
    checking_account.refresh_from_db()
    assert checking_account.is_active is True  # toujours actif

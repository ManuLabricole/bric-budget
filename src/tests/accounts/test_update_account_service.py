"""
tests/accounts/test_update_account_service.py — service update_account/archive_account (#292).

La couche HTTP est testée dans tests/patrimoine/test_account_edit.py ; ici on teste
les invariants du SERVICE : persistance des champs + *Details, IBAN jamais écrasé
par omission (édition partielle), identité d'import obligatoire, soft-delete.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from accounts.services import archive_account, update_account
from tests.factories import (
    AccountFactory,
    CheckingAccountFactory,
    SavingsAccountFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_update_account_persists_name_currency_and_iban():
    user = UserFactory()
    account = AccountFactory(
        members=[user],
        account_type="checking",
        currency="CHF",
        iban=None,
        contract_number="OLD-123",
    )
    CheckingAccountFactory(account=account, bic="")

    # Le service reçoit des type_fields DÉJÀ normalisés par la vue (comme
    # create_account) — pas de parsing ici.
    update_account(
        account=account,
        name="Compte courant V2",
        currency="EUR",
        contract_number="OLD-123",
        iban="CH5604835012345678009",
        bic="BCVLCH2L",
    )

    account.refresh_from_db()
    assert account.name == "Compte courant V2"
    assert account.currency == "EUR"
    assert account.iban == "CH5604835012345678009"
    assert account.checking_account.bic == "BCVLCH2L"


@pytest.mark.django_db
def test_update_savings_without_iban_field_keeps_existing_iban():
    """Le form savings n'a pas de champ IBAN → omission ne doit PAS l'effacer."""
    user = UserFactory()
    account = AccountFactory(
        members=[user],
        account_type="savings",
        currency="CHF",
        iban="CH5604835012345678009",
    )
    SavingsAccountFactory(account=account, interest_rate=Decimal("1.00"))

    # type_fields sans "iban" (comme _parse_type_fields(savings) le renvoie).
    update_account(
        account=account,
        name="Livret renommé",
        currency="CHF",
        contract_number="",
        interest_rate=Decimal("2.50"),
    )

    account.refresh_from_db()
    assert account.iban == "CH5604835012345678009"  # conservé, pas écrasé
    assert account.name == "Livret renommé"
    assert account.savings_account.interest_rate == Decimal("2.50")


@pytest.mark.django_db
def test_update_account_requires_iban_or_contract_number():
    user = UserFactory()
    account = AccountFactory(
        members=[user],
        account_type="checking",
        iban=None,
        contract_number="C-1",
    )
    CheckingAccountFactory(account=account)

    with pytest.raises(ValidationError):
        update_account(
            account=account,
            name="X",
            currency="CHF",
            contract_number="",
            iban="",
            bic="",
        )

    account.refresh_from_db()
    assert account.contract_number == "C-1"  # rien persisté (atomique)
    assert account.name != "X"  # le nom assigné avant le raise n'a pas fui


@pytest.mark.django_db
def test_archive_account_sets_is_active_false():
    user = UserFactory()
    account = AccountFactory(members=[user], iban=None, contract_number="C-1")

    archive_account(account)

    account.refresh_from_db()
    assert account.is_active is False

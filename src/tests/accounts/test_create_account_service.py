"""
tests/accounts/test_create_account_service.py — service create_account (wizard #73).

LE point d'entrée de création d'une enveloppe : Account + *Details (dispatch par
type) + membership, le tout atomique. Les invariants de champ restent sur le
modèle (Account.clean() — pension ⇒ CHF) : on vérifie ici que le service les
APPLIQUE (full_clean — que objects.create() ne déclenche pas) et que rien ne
persiste en cas d'échec, même après le save de l'Account (rollback).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import (
    Account,
    CheckingAccount,
    Institution,
    LifeInsuranceDetails,
    PensionDetails,
    SavingsAccount,
)
from accounts.services import create_account


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="manu@wizard-test.ch", password="pass"
    )


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(
        email="carys@wizard-test.ch", password="pass"
    )


@pytest.fixture
def institution(db):
    # Pas de domain → le post_save logo ne tente aucun fetch (cf. test_logo_signal).
    return Institution.objects.create(
        name="Yuh", slug="yuh", country="CH", default_currency="CHF"
    )


@pytest.mark.django_db
def test_checking_creates_account_details_and_account_iban(user, institution):
    account = create_account(
        user=user,
        institution=institution,
        account_type="checking",
        name="Compte courant",
        currency="CHF",
        opened_at=date(2024, 1, 15),
        iban="CH5604835012345678009",
        bic="YUHHCHZZ",
    )

    assert account.opened_at == date(2024, 1, 15)
    # L'IBAN vit UNIQUEMENT sur Account (source de vérité, #82) ; CheckingAccount
    # ne porte plus que le BIC — décision actée 2026-06-10, consolidée #82.
    assert account.iban == "CH5604835012345678009"
    details = CheckingAccount.objects.get(account=account)
    assert details.bic == "YUHHCHZZ"


@pytest.mark.django_db
def test_savings_creates_savings_details(user, institution):
    account = create_account(
        user=user,
        institution=institution,
        account_type="savings",
        name="Livret",
        currency="EUR",
        contract_number="LIV-1",
        interest_rate=Decimal("3.00"),
    )

    details = SavingsAccount.objects.get(account=account)
    assert details.interest_rate == Decimal("3.00")


@pytest.mark.django_db
def test_savings_without_rate_defaults_to_zero(user, institution):
    """interest_rate est NOT NULL (default=0) : None ne doit pas exploser."""
    account = create_account(
        user=user,
        institution=institution,
        account_type="savings",
        name="Livret",
        currency="EUR",
        contract_number="LIV-2",
    )

    assert SavingsAccount.objects.get(account=account).interest_rate == Decimal("0")


@pytest.mark.django_db
def test_insurance_creates_life_insurance_details(user, institution):
    account = create_account(
        user=user,
        institution=institution,
        account_type="insurance",
        name="AV",
        currency="EUR",
        contract_number="AV-0000001",
        fonds_euro_balance=Decimal("10000.00"),
        fonds_euro_rate=Decimal("2.30"),
        management_fee_pct=Decimal("0.50"),
    )

    # Identité d'import : le n° de contrat vaut pour tous les types (pas que checking).
    assert account.contract_number == "AV-0000001"
    details = LifeInsuranceDetails.objects.get(account=account)
    assert details.fonds_euro_balance == Decimal("10000.00")
    assert details.fonds_euro_rate == Decimal("2.30")
    assert details.management_fee_pct == Decimal("0.50")


@pytest.mark.django_db
def test_pension_creates_pension_details(user, institution):
    account = create_account(
        user=user,
        institution=institution,
        account_type="pension_3a",
        name="3a",
        currency="CHF",
        contract_number="3A-1",
        annual_limit_chf=Decimal("7056.00"),
    )

    details = PensionDetails.objects.get(account=account)
    assert details.annual_limit_chf == Decimal("7056.00")


@pytest.mark.django_db
def test_brokerage_creates_account_only(user, institution):
    account = create_account(
        user=user,
        institution=institution,
        account_type="brokerage",
        name="Titres",
        currency="CHF",
        contract_number="BRK-1",
    )

    assert not CheckingAccount.objects.filter(account=account).exists()
    assert not SavingsAccount.objects.filter(account=account).exists()
    assert not LifeInsuranceDetails.objects.filter(account=account).exists()
    assert not PensionDetails.objects.filter(account=account).exists()


@pytest.mark.django_db
def test_member_is_creator_and_for_user_scoping(user, other_user, institution):
    account = create_account(
        user=user,
        institution=institution,
        account_type="crypto",
        name="Binance",
        currency="USD",
        contract_number="CRY-1",
    )

    # IDOR (SR-001) : visible pour le créateur, invisible pour un autre user.
    assert Account.objects.for_user(user).filter(pk=account.pk).exists()
    assert not Account.objects.for_user(other_user).filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_pension_eur_rejected_nothing_persisted(user, institution):
    with pytest.raises(ValidationError):
        create_account(
            user=user,
            institution=institution,
            account_type="pension_3a",
            name="3a",
            currency="EUR",
            contract_number="3A-2",
        )

    assert Account.objects.count() == 0
    assert PensionDetails.objects.count() == 0


@pytest.mark.django_db
def test_unknown_account_type_rejected(user, institution):
    with pytest.raises(ValidationError):
        create_account(
            user=user,
            institution=institution,
            account_type="yolo",
            name="X",
            currency="CHF",
            contract_number="X-1",
        )

    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_duplicate_iban_rejected(user, institution):
    create_account(
        user=user,
        institution=institution,
        account_type="checking",
        name="A",
        currency="CHF",
        iban="CH5604835012345678009",
    )

    with pytest.raises(ValidationError):
        create_account(
            user=user,
            institution=institution,
            account_type="checking",
            name="B",
            currency="CHF",
            iban="CH5604835012345678009",
        )

    assert Account.objects.count() == 1


@pytest.mark.django_db
def test_empty_iban_stored_as_none(user, institution):
    """'' → None sinon IntegrityError sur le 2e compte sans IBAN (unique=True)."""
    a = create_account(
        user=user,
        institution=institution,
        account_type="checking",
        name="A",
        currency="CHF",
        iban="",
        contract_number="C-A",
    )
    b = create_account(
        user=user,
        institution=institution,
        account_type="checking",
        name="B",
        currency="CHF",
        iban="",
        contract_number="C-B",
    )

    assert a.iban is None
    assert b.iban is None


@pytest.mark.django_db
def test_details_failure_rolls_back_account(user, institution):
    """Échec sur le Details APRÈS le save de l'Account → tout annulé (atomicité)."""
    with pytest.raises(ValidationError):
        create_account(
            user=user,
            institution=institution,
            account_type="savings",
            name="Livret",
            currency="EUR",
            contract_number="LIV-3",
            interest_rate=Decimal("123456.78"),  # max_digits=5 → invalide
        )

    assert Account.objects.count() == 0
    assert SavingsAccount.objects.count() == 0


@pytest.mark.django_db
def test_missing_identifier_rejected(user, institution):
    """Ni IBAN ni n° de contrat → refus : le compte serait inrattachable aux imports."""
    with pytest.raises(ValidationError):
        create_account(
            user=user,
            institution=institution,
            account_type="savings",
            name="Livret orphelin",
            currency="EUR",
        )

    assert Account.objects.count() == 0

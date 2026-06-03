"""
tests/accounts/test_details_3a.py

Phase 3A (#72) — sous-modèles Details (OneToOne → Account) :
LifeInsuranceDetails (fonds euro) et PensionDetails (3a/LPP).

TDD : ROUGE tant que les modèles n'existent pas. Montants en Decimal(str(...))
(SR-002 — jamais Decimal(float)).
"""

from decimal import Decimal

import pytest

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@det3a-test.ch", password="pass"
    )


@pytest.fixture
def institution(db):
    from accounts.models import Institution

    return Institution.objects.create(
        name="Det CH 3A",
        slug="det-ch-3a",
        country="CH",
        default_currency="CHF",
    )


@pytest.fixture
def av_account(db, institution, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=institution,
        name="AV Boursorama",
        account_type="insurance",
        currency="EUR",
    )
    acc.members.add(user_a)
    return acc


@pytest.fixture
def pension_account(db, institution, user_a):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=institution,
        name="3a Finpension",
        account_type="pension_3a",
        currency="CHF",
    )
    acc.members.add(user_a)
    return acc


# =============================================================================
# LifeInsuranceDetails — fonds euro = bucket "Fonds euros" (pas un Asset)
# =============================================================================


def test_life_insurance_details_created(av_account):
    from accounts.models import LifeInsuranceDetails

    det = LifeInsuranceDetails.objects.create(
        account=av_account,
        fonds_euro_balance=Decimal(str(12000.50)),
        fonds_euro_rate=Decimal(str(2.30)),
        management_fee_pct=Decimal(str(0.60)),
    )
    # accès depuis le compte (OneToOne)
    assert av_account.life_insurance_details == det
    assert det.fonds_euro_balance == Decimal("12000.50")
    assert det.fonds_euro_rate == Decimal("2.30")
    assert det.management_fee_pct == Decimal("0.60")


def test_life_insurance_details_optional_fields(av_account):
    from accounts.models import LifeInsuranceDetails

    det = LifeInsuranceDetails.objects.create(account=av_account)
    assert det.fonds_euro_balance is None
    assert det.fonds_euro_rate is None


# =============================================================================
# PensionDetails — 3a / LPP (plafond, versements, frais)
# =============================================================================


def test_pension_details_created(pension_account):
    from accounts.models import PensionDetails

    det = PensionDetails.objects.create(
        account=pension_account,
        annual_limit_chf=Decimal(str(7056.00)),
        contributions_ytd=Decimal(str(3000.00)),
        management_fee_pct=Decimal(str(0.39)),
    )
    assert pension_account.pension_details == det
    assert det.annual_limit_chf == Decimal("7056.00")
    assert det.contributions_ytd == Decimal("3000.00")


def test_pension_details_optional_fields(pension_account):
    from accounts.models import PensionDetails

    det = PensionDetails.objects.create(account=pension_account)
    assert det.annual_limit_chf is None
    assert det.contributions_ytd is None

"""
tests/accounts/test_account_extensions_3a.py

Phase 3A (#72) — extensions Account : opened_at / closed_at / fiscal_country,
account_type=crypto, validation devise par type, IDOR par type.

TDD (feedback_dex_workflow) : écrit AVANT les migrations → ROUGE tant que les
champs/valeurs n'existent pas.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_a(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="usera@ext3a-test.ch", password="pass"
    )


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email="userb@ext3a-test.ch", password="pass"
    )


@pytest.fixture
def institution_ch(db):
    from accounts.models import Institution

    return Institution.objects.create(
        name="Test CH 3A",
        slug="test-ch-ext3a",
        country="CH",
        default_currency="CHF",
    )


def _make_account(institution, user, **kwargs):
    from accounts.models import Account

    defaults = {"name": "Compte", "account_type": "checking", "currency": "CHF"}
    defaults.update(kwargs)
    acc = Account.objects.create(institution=institution, **defaults)
    acc.members.add(user)
    return acc


# =============================================================================
# Nouveaux champs : opened_at / closed_at / fiscal_country
# =============================================================================


def test_opened_closed_at_stored(institution_ch, user_a):
    acc = _make_account(
        institution_ch,
        user_a,
        opened_at=datetime.date(2018, 1, 1),
        closed_at=datetime.date(2025, 6, 1),
    )
    acc.refresh_from_db()
    assert acc.opened_at == datetime.date(2018, 1, 1)
    assert acc.closed_at == datetime.date(2025, 6, 1)


def test_opened_closed_at_nullable(institution_ch, user_a):
    acc = _make_account(institution_ch, user_a)
    assert acc.opened_at is None
    assert acc.closed_at is None


def test_fiscal_country_defaults_to_institution_country(institution_ch, user_a):
    # fiscal_country non fourni → doit retomber sur institution.country (CH)
    acc = _make_account(institution_ch, user_a)
    acc.refresh_from_db()
    assert acc.fiscal_country == "CH"


def test_fiscal_country_explicit_is_kept(institution_ch, user_a):
    # un compte FR ouvert chez une institution CH garde FR
    acc = _make_account(institution_ch, user_a, fiscal_country="FR")
    acc.refresh_from_db()
    assert acc.fiscal_country == "FR"


# =============================================================================
# account_type : crypto ajouté
# =============================================================================


def test_crypto_account_type_exists():
    from accounts.models import Account

    assert "crypto" in Account.AccountType.values


def test_create_crypto_account(institution_ch, user_a):
    acc = _make_account(institution_ch, user_a, account_type="crypto")
    acc.refresh_from_db()
    assert acc.account_type == "crypto"


# =============================================================================
# Validation devise par type (pension → CHF obligatoire)
# =============================================================================


@pytest.mark.parametrize("ptype", ["pension_3a", "pension_lp"])
def test_pension_rejects_non_chf(institution_ch, ptype):
    from accounts.models import Account

    acc = Account(
        institution=institution_ch,
        name="Pension",
        account_type=ptype,
        currency="EUR",
    )
    with pytest.raises(ValidationError):
        acc.full_clean()


@pytest.mark.parametrize("ptype", ["pension_3a", "pension_lp"])
def test_pension_accepts_chf(institution_ch, ptype):
    from accounts.models import Account

    acc = Account(
        institution=institution_ch,
        name="Pension",
        account_type=ptype,
        currency="CHF",
    )
    acc.full_clean()  # ne doit pas lever


def test_checking_accepts_eur(institution_ch):
    from accounts.models import Account

    acc = Account(
        institution=institution_ch,
        name="Courant",
        account_type="checking",
        currency="EUR",
    )
    acc.full_clean()  # ne doit pas lever


# =============================================================================
# IDOR par type (for_user scope tous les types)
# =============================================================================


@pytest.mark.parametrize(
    "ptype", ["checking", "savings", "insurance", "pension_3a", "crypto"]
)
def test_for_user_isolates_each_type(institution_ch, user_a, user_b, ptype):
    from accounts.models import Account

    acc = _make_account(institution_ch, user_a, account_type=ptype, name=f"A-{ptype}")
    assert Account.objects.for_user(user_a).filter(pk=acc.pk).exists()
    assert not Account.objects.for_user(user_b).filter(pk=acc.pk).exists()

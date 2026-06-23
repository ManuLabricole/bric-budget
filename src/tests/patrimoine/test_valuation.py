"""
tests/patrimoine/test_valuation.py — frontière de valorisation (TDD).

`valuation` est la SEULE porte d'entrée des vues/bilan vers la valeur d'un compte ou
le net worth. Implémentation actuelle = moteur à la volée ; remplaçable par des
PortfolioSnapshot matérialisés (#92) sans changer les appelants.
"""

import datetime
from decimal import Decimal

import pytest

from patrimoine.services.valuation import current_value, net_worth_series


def _d(s):
    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


@pytest.mark.django_db
def test_current_value_is_latest_anchor_chf(chf_account, make_snapshot, make_tx):
    """Valeur courante = ancre CHF marchée jusqu'à `on` (inclut les tx postérieures)."""
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_tx(chf_account, "2026-03-11", -40, amount_chf=-40)
    assert current_value(chf_account, on=_d("2026-03-10")) == Decimal("1000")
    assert current_value(chf_account, on=_d("2026-03-12")) == Decimal("960")


@pytest.mark.django_db
def test_current_value_none_without_anchor(chf_account, make_tx):
    """Compte sans snapshot → solde absolu inconnu → None (jamais un 0 trompeur)."""
    make_tx(chf_account, "2026-03-11", 100, amount_chf=100)
    assert current_value(chf_account, on=_d("2026-03-12")) is None


@pytest.mark.django_db
def test_current_value_none_when_chf_conversion_missing(eur_account, make_snapshot):
    """balance_chf NULL (taux pas encore calculé) → None, pas une valeur inventée."""
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=None)
    assert current_value(eur_account, on=_d("2026-03-10")) is None


@pytest.mark.django_db
def test_current_value_eur_account_returns_chf_anchor(eur_account, make_snapshot):
    """Compte EUR avec balance_chf converti → renvoie la valeur CHF (pas l'EUR brut,
    pas None). Régression #118 : dès que l'import convertit le solde, il s'affiche."""
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=480)
    assert current_value(eur_account, on=_d("2026-03-10")) == Decimal("480")


@pytest.mark.django_db
def test_net_worth_series_sums_accounts_in_chf(chf_account, eur_account, make_snapshot):
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=480)
    s = net_worth_series([chf_account, eur_account], _d("2026-03-10"), _d("2026-03-10"))
    assert s.values[0] == Decimal("1480")
    assert s.complete is True

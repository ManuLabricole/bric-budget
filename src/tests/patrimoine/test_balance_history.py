"""
tests/patrimoine/test_balance_history.py — moteur d'ancrage du solde.

TDD (feedback_dex_workflow) : écrits AVANT l'implémentation → ROUGE d'abord.

Sémantique testée :
  - chaque point = solde de FIN de journée (inclut les tx du jour).
  - sur la date d'un snapshot → exactement la valeur banque (re-ancrage).
  - la dérive (Σ tx ≠ écart de soldes) est absorbée à l'ancre, jamais cumulée.
  - compte sans snapshot → série relative + anchored=False.
"""

import datetime
from decimal import Decimal

import pytest

from patrimoine.services.balance_history import (
    BalanceSeries,
    account_balance_series,
    consolidated_balance_series,
    period_bounds,
)


def _d(s):
    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


def _value_on(series: BalanceSeries, date_str):
    """Solde du jour `date_str` dans la série."""
    target = _d(date_str)
    for dt, val in zip(series.dates, series.values):
        if dt == target:
            return val
    raise AssertionError(f"{date_str} absent de la série")


# =============================================================================
# Marche depuis une ancre unique
# =============================================================================


@pytest.mark.django_db
def test_snapshot_date_shows_bank_value(chf_account, make_snapshot):
    """Sur la date du snapshot, le solde = valeur banque exacte (pas de tx ajoutée)."""
    make_snapshot(chf_account, "2026-03-10", balance=1000)
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-10"))
    assert _value_on(s, "2026-03-10") == Decimal("1000")
    assert s.anchored is True


@pytest.mark.django_db
def test_forward_walk_adds_transactions(chf_account, make_snapshot, make_tx):
    """Après l'ancre, le solde cumule les transactions (signe inclus)."""
    make_snapshot(chf_account, "2026-03-10", balance=1000)
    make_tx(chf_account, "2026-03-11", -40)  # débit
    make_tx(chf_account, "2026-03-12", 100)  # crédit
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-13"))
    assert _value_on(s, "2026-03-10") == Decimal("1000")
    assert _value_on(s, "2026-03-11") == Decimal("960")
    assert _value_on(s, "2026-03-12") == Decimal("1060")
    assert _value_on(s, "2026-03-13") == Decimal("1060")  # pas de tx → plat


@pytest.mark.django_db
def test_backward_walk_undoes_transactions(chf_account, make_snapshot, make_tx):
    """Avant l'ancre, on défait les transactions postérieures (marche arrière)."""
    make_snapshot(chf_account, "2026-03-10", balance=1000)
    make_tx(chf_account, "2026-03-10", 200)  # déjà inclus dans le snapshot
    make_tx(chf_account, "2026-03-09", -50)
    s = account_balance_series(chf_account, _d("2026-03-08"), _d("2026-03-10"))
    # 2026-03-10 = 1000 (banque). On retire le +200 du 10 → 800 au soir du 09.
    assert _value_on(s, "2026-03-09") == Decimal("800")
    # On retire le -50 du 09 → 850 au soir du 08.
    assert _value_on(s, "2026-03-08") == Decimal("850")


@pytest.mark.django_db
def test_balance_values_are_decimal(chf_account, make_snapshot, make_tx):
    """SR-002 : jamais de float dans la série."""
    make_snapshot(chf_account, "2026-03-10", balance=1000)
    make_tx(chf_account, "2026-03-11", "-12.34")
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-11"))
    assert all(isinstance(v, Decimal) for v in s.values)


# =============================================================================
# Ré-ancrage entre deux snapshots (la dérive ne s'accumule pas)
# =============================================================================


@pytest.mark.django_db
def test_reanchors_on_each_snapshot(chf_account, make_snapshot, make_tx):
    """
    A=100 au 10, B=200 au 20, mais seulement +50 de tx entre les deux.
    → la veille de B : 150 (marche depuis A). Sur B : 200 (re-ancré, pas 150).
    Les 50 de dérive sont absorbés à l'ancre B, jamais propagés.
    """
    make_snapshot(chf_account, "2026-01-10", balance=100)
    make_snapshot(chf_account, "2026-01-20", balance=200)
    make_tx(chf_account, "2026-01-15", 50)
    s = account_balance_series(chf_account, _d("2026-01-10"), _d("2026-01-25"))
    assert _value_on(s, "2026-01-15") == Decimal("150")  # ancré sur A
    assert _value_on(s, "2026-01-19") == Decimal("150")
    assert _value_on(s, "2026-01-20") == Decimal("200")  # re-ancré sur B
    assert _value_on(s, "2026-01-25") == Decimal("200")  # plat après B


@pytest.mark.django_db
def test_drift_is_bounded_not_accumulated(chf_account, make_snapshot, make_tx):
    """
    Trois ancres, dérive à chaque segment. Chaque ancre doit afficher SA valeur
    banque exacte — la dérive du segment précédent ne déborde jamais sur le suivant.
    """
    make_snapshot(chf_account, "2026-01-01", balance=1000)
    make_snapshot(chf_account, "2026-02-01", balance=1500)  # +500 banque
    make_snapshot(chf_account, "2026-03-01", balance=1200)  # -300 banque
    make_tx(chf_account, "2026-01-15", 100)  # segment 1 : +100 seulement (dérive 400)
    make_tx(chf_account, "2026-02-15", -50)  # segment 2 : -50 seulement (dérive -250)
    s = account_balance_series(chf_account, _d("2026-01-01"), _d("2026-03-01"))
    assert _value_on(s, "2026-01-01") == Decimal("1000")
    assert _value_on(s, "2026-02-01") == Decimal("1500")
    assert _value_on(s, "2026-03-01") == Decimal("1200")


@pytest.mark.django_db
def test_authoritative_falls_back_to_computed(chf_account, make_snapshot):
    """Snapshot sans balance extraite → on utilise computed_balance comme ancre."""
    make_snapshot(chf_account, "2026-03-10", balance=None, computed=777)
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-10"))
    assert _value_on(s, "2026-03-10") == Decimal("777")


# =============================================================================
# Compte sans ancre
# =============================================================================


@pytest.mark.django_db
def test_no_snapshot_is_unanchored(chf_account, make_tx):
    """Compte avec tx mais 0 snapshot → anchored=False (solde absolu inconnu)."""
    make_tx(chf_account, "2026-03-11", 100)
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-12"))
    assert s.anchored is False


@pytest.mark.django_db
def test_no_data_at_all_is_unanchored_flat_zero(chf_account):
    """Compte vide (ni snapshot ni tx) → série à 0, anchored=False, pas de crash."""
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-12"))
    assert s.anchored is False
    assert all(v == Decimal("0") for v in s.values)


# =============================================================================
# Couverture temporelle : un point par jour, bornes incluses
# =============================================================================


@pytest.mark.django_db
def test_series_has_one_point_per_day(chf_account, make_snapshot):
    make_snapshot(chf_account, "2026-03-10", balance=1000)
    s = account_balance_series(chf_account, _d("2026-03-10"), _d("2026-03-14"))
    assert s.dates == [
        _d("2026-03-10"),
        _d("2026-03-11"),
        _d("2026-03-12"),
        _d("2026-03-13"),
        _d("2026-03-14"),
    ]
    assert len(s.values) == len(s.dates)


# =============================================================================
# Consolidation multi-devises en CHF
# =============================================================================


@pytest.mark.django_db
def test_consolidated_sums_accounts_in_chf(
    chf_account, eur_account, make_snapshot, make_tx
):
    """
    CHF : 1000. EUR : 500 € → balance_chf = 480 CHF.
    Consolidé = 1480 CHF (somme des valeurs CHF, pas des valeurs natives).
    """
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=480)
    s = consolidated_balance_series(
        [chf_account, eur_account], _d("2026-03-10"), _d("2026-03-10")
    )
    assert _value_on(s, "2026-03-10") == Decimal("1480")


@pytest.mark.django_db
def test_account_series_in_chf_uses_chf_fields(eur_account, make_snapshot, make_tx):
    """in_chf=True → ancre sur balance_chf et marche sur amount_chf."""
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=480)
    make_tx(eur_account, "2026-03-11", amount=100, amount_chf=96)
    s = account_balance_series(
        eur_account, _d("2026-03-10"), _d("2026-03-11"), in_chf=True
    )
    assert _value_on(s, "2026-03-10") == Decimal("480")
    assert _value_on(s, "2026-03-11") == Decimal("576")


# =============================================================================
# complete : balance_chf manquant ne doit PAS être ancré à 0 en silence
# =============================================================================


@pytest.mark.django_db
def test_complete_true_when_all_anchors_present(chf_account, make_snapshot):
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    s = account_balance_series(
        chf_account, _d("2026-03-10"), _d("2026-03-10"), in_chf=True
    )
    assert s.complete is True


@pytest.mark.django_db
def test_account_in_chf_incomplete_when_balance_chf_null(eur_account, make_snapshot):
    """Conversion CHF pas encore calculée (balance_chf=None) → complete=False, pas un 0 silencieux."""
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=None)
    s = account_balance_series(
        eur_account, _d("2026-03-10"), _d("2026-03-10"), in_chf=True
    )
    assert s.complete is False


@pytest.mark.django_db
def test_consolidated_incomplete_if_any_account_missing_chf(
    chf_account, eur_account, make_snapshot
):
    """Un compte EUR sans taux ne disparaît plus en silence : la conso est signalée incomplète."""
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=None)
    s = consolidated_balance_series(
        [chf_account, eur_account], _d("2026-03-10"), _d("2026-03-10")
    )
    assert s.complete is False


# =============================================================================
# period_bounds — fenêtres temporelles
# =============================================================================


def test_period_bounds_ytd_cuts_at_jan_first():
    start, end = period_bounds("ytd", today=_d("2026-06-04"))
    assert start == _d("2026-01-01")
    assert end == _d("2026-06-04")


def test_period_bounds_windows():
    today = _d("2026-06-04")
    assert period_bounds("1j", today=today)[0] == _d("2026-06-03")
    assert period_bounds("7j", today=today)[0] == _d("2026-05-28")
    assert period_bounds("1m", today=today)[0] == _d("2026-05-04")
    assert period_bounds("1a", today=today)[0] == _d("2025-06-04")


def test_period_bounds_tout_uses_earliest():
    start, end = period_bounds(
        "tout", today=_d("2026-06-04"), earliest=_d("2022-10-18")
    )
    assert start == _d("2022-10-18")
    assert end == _d("2026-06-04")


def test_period_bounds_tout_without_earliest_is_single_day():
    """'tout' sans plus ancienne transaction connue → série d'un seul jour (start=end=today)."""
    start, end = period_bounds("tout", today=_d("2026-06-04"))
    assert start == _d("2026-06-04")
    assert end == _d("2026-06-04")


def test_period_bounds_month_clamp_on_31st():
    """1m/3m depuis un 31 → jour clampé au dernier jour valide du mois cible (pas de crash)."""
    # 31 mars - 1 mois → 28 février (2026 non bissextile), pas 31 février.
    assert period_bounds("1m", today=_d("2026-03-31"))[0] == _d("2026-02-28")
    # 31 mai - 3 mois → 28 février également.
    assert period_bounds("3m", today=_d("2026-05-31"))[0] == _d("2026-02-28")

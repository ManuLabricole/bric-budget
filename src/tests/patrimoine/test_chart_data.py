"""
tests/patrimoine/test_chart_data.py — données JSON pour la courbe et la distribution (TDD).

Decimal en interne, float seulement à la frontière JSON (SR-002).
"""

import datetime

import pytest

from patrimoine.services.bilan import overview_bilan
from patrimoine.services.chart_data import (
    _STACK_PALETTE,
    account_class_series,
    chart_series,
    distribution,
)


def _d(s):
    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


@pytest.fixture
def savings_account(db, chf_institution, user):
    from accounts.models import Account

    acc = Account.objects.create(
        institution=chf_institution,
        name="Livret CHF",
        account_type="savings",
        currency="CHF",
    )
    acc.members.add(user)
    return acc


@pytest.mark.django_db
def test_chart_series_shape_and_total(chf_account, savings_account, make_snapshot):
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(savings_account, "2026-03-10", balance=500, balance_chf=500)
    data = chart_series(
        [chf_account, savings_account], _d("2026-03-10"), _d("2026-03-10")
    )

    assert data["dates"] == ["2026-03-10"]
    assert data["total"] == [1500.0]  # float à la frontière JSON
    # Une série par classe fonctionnelle ayant des comptes.
    names = {s["name"] for s in data["series"]}
    assert names == {"Comptes courants", "Livrets"}
    assert all("color" in s and "values" in s for s in data["series"])
    assert data["complete"] is True


@pytest.mark.django_db
def test_chart_series_flags_incomplete_on_missing_chf(eur_account, make_snapshot):
    make_snapshot(eur_account, "2026-03-10", balance=500, balance_chf=None)
    data = chart_series([eur_account], _d("2026-03-10"), _d("2026-03-10"))
    assert data["complete"] is False


@pytest.mark.django_db
def test_account_class_series_uses_stored_colour_hex(
    chf_account, savings_account, make_snapshot
):
    """#134 : la série d'un compte est colorée par sa colour_hex stockée (pas le cyclique)."""
    chf_account.colour_hex = "#abcdef"
    chf_account.save(update_fields=["colour_hex"])
    savings_account.colour_hex = "#fedcba"
    savings_account.save(update_fields=["colour_hex"])

    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(savings_account, "2026-03-10", balance=500, balance_chf=500)

    data = account_class_series(
        [chf_account, savings_account], _d("2026-03-10"), _d("2026-03-10")
    )
    by_name = {s["name"]: s["color"] for s in data["series"]}
    assert by_name[chf_account.name] == "#abcdef"
    assert by_name[savings_account.name] == "#fedcba"


@pytest.mark.django_db
def test_account_class_series_falls_back_when_colour_hex_empty(
    chf_account, make_snapshot
):
    """Filet : compte sans colour_hex (legacy) → couleur _STACK_PALETTE, jamais vide."""
    assert chf_account.colour_hex == ""  # créé sans allocation (fixture brute)
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)

    data = account_class_series([chf_account], _d("2026-03-10"), _d("2026-03-10"))
    assert data["series"][0]["color"] == _STACK_PALETTE[0]


@pytest.mark.django_db
def test_distribution_from_nodes(chf_account, savings_account, make_snapshot):
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(savings_account, "2026-03-10", balance=500, balance_chf=500)
    nodes = overview_bilan([chf_account, savings_account], on=_d("2026-03-10"))
    dist = distribution(nodes)

    assert dist["total"] == 1500.0
    segs = {s["name"]: s for s in dist["segments"]}
    assert segs["Comptes courants"]["value"] == 1000.0
    assert segs["Comptes courants"]["itemStyle"]["color"]  # shape ECharts
    # Les classes à valeur nulle / SOON n'apparaissent pas dans le donut.
    assert "Crypto" not in segs

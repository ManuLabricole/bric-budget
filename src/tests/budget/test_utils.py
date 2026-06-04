"""
tests/budget/test_utils.py

Tests unitaires pour budget/utils.py.

Couvre toutes les fonctions pures/quasi-pures extraites lors du Plan C.
Ces tests pinnent le comportement — toute modification de utils.py qui
casse un de ces tests est une régression intentionnelle à valider.
"""

from datetime import date

import pytest
from django.db.models import Q

from budget.utils import (
    _add_months,
    _generate_unique_slug,
    _gradient,
    _keyword_q,
    _period_end_from_start,
    _period_from_session,
    _rgba,
    _seg_factor,
    _vary_color,
)

# =============================================================================
# _add_months
# =============================================================================


def test_add_months_normal():
    assert _add_months(date(2026, 3, 1), 1) == date(2026, 4, 1)


def test_add_months_end_of_month_clamps():
    """31 janvier + 1 mois → 28 février (pas 31 février)."""
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_add_months_end_of_month_clamps_leap_year():
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_add_months_year_boundary():
    assert _add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_add_months_negative():
    assert _add_months(date(2026, 3, 15), -1) == date(2026, 2, 15)


def test_add_months_negative_year_boundary():
    assert _add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)


def test_add_months_zero():
    assert _add_months(date(2026, 4, 15), 0) == date(2026, 4, 15)


def test_add_months_twelve():
    assert _add_months(date(2026, 4, 1), 12) == date(2027, 4, 1)


# =============================================================================
# _period_end_from_start
# =============================================================================


def test_period_end_from_start_1m():
    assert _period_end_from_start(date(2026, 4, 1), "1m") == date(2026, 4, 30)


def test_period_end_from_start_1m_february():
    assert _period_end_from_start(date(2026, 2, 1), "1m") == date(2026, 2, 28)


def test_period_end_from_start_3m():
    """Avril + 3m → fin juin."""
    assert _period_end_from_start(date(2026, 4, 1), "3m") == date(2026, 6, 30)


def test_period_end_from_start_3m_from_february():
    """Février + 3m → fin avril."""
    assert _period_end_from_start(date(2026, 2, 1), "3m") == date(2026, 4, 30)


def test_period_end_from_start_1y():
    """Avril 2026 + 12m → fin mars 2027."""
    assert _period_end_from_start(date(2026, 4, 1), "1y") == date(2027, 3, 31)


# =============================================================================
# _period_from_session
# =============================================================================


def test_period_from_session_reads_stored_dates():
    session = {
        "budget_period_start": "2026-04-01",
        "budget_period_end": "2026-04-30",
    }
    start, end = _period_from_session(session)
    assert start == date(2026, 4, 1)
    assert end == date(2026, 4, 30)


def test_period_from_session_empty_falls_back_to_current_month():
    start, end = _period_from_session({})
    today = date.today()
    assert start == today.replace(day=1)
    assert start.month == end.month
    assert end.day >= 28


def test_period_from_session_partial_falls_back():
    """Si seulement start est en session → fallback mois courant."""
    start, end = _period_from_session({"budget_period_start": "2026-04-01"})
    today = date.today()
    assert start == today.replace(day=1)


# =============================================================================
# _keyword_q — construction du filtre Q (sans DB)
# =============================================================================


def test_keyword_q_empty_returns_no_match():
    q = _keyword_q("")
    assert q == Q(pk__in=[])


def test_keyword_q_whitespace_only_returns_no_match():
    q = _keyword_q("   ")
    assert q == Q(pk__in=[])


def test_keyword_q_single_word_builds_iregex():
    q = _keyword_q("MIGROS")
    assert "iregex" in str(q)
    assert "MIGROS" in str(q)


def test_keyword_q_word_boundary_pattern():
    """Le pattern doit contenir \\y pour les word boundaries PostgreSQL."""
    q = _keyword_q("ESSO")
    assert r"\y" in str(q)


def test_keyword_q_multi_word_is_and():
    """Deux mots → deux conditions AND dans le Q."""
    q = _keyword_q("MIGROS ZURICH")
    q_str = str(q)
    assert "MIGROS" in q_str
    assert "ZURICH" in q_str


def test_keyword_q_normalizes_to_uppercase():
    q_lower = _keyword_q("migros")
    q_upper = _keyword_q("MIGROS")
    assert str(q_lower) == str(q_upper)


# =============================================================================
# _keyword_q — comportement word-boundary avec vrai DB
# =============================================================================


@pytest.mark.django_db
def test_keyword_q_word_boundary_no_partial_match(django_user_model):
    """ESSO ne doit PAS matcher ESSOF108 (word boundary \\y PostgreSQL)."""
    from django.contrib.auth import get_user_model

    from accounts.models import Account, Institution
    from transactions.models import Transaction

    User = get_user_model()
    user = User.objects.create_user(email="kwboundary@test.ch", password="pass")
    bank = Institution.objects.create(
        name="Test Bank", slug="test-bank-kw", country="CH", default_currency="CHF"
    )
    acc = Account.objects.create(
        institution=bank, name="KW Test", account_type="checking", currency="CHF"
    )
    acc.members.add(user)

    Transaction.objects.create(
        account=acc,
        date=date(2026, 4, 1),
        amount=-10,
        display_name="ESSOF108 STATION",
        description_raw="ESSOF108 STATION",
        currency="CHF",
    )

    qs = Transaction.objects.filter(_keyword_q("ESSO"))
    assert qs.count() == 0


@pytest.mark.django_db
def test_keyword_q_exact_word_matches(django_user_model):
    """ESSO DOIT matcher 'ESSO STATION' (mot entier)."""
    from django.contrib.auth import get_user_model

    from accounts.models import Account, Institution
    from transactions.models import Transaction

    User = get_user_model()
    user = User.objects.create_user(email="kwexact@test.ch", password="pass")
    bank = Institution.objects.create(
        name="Test Bank2", slug="test-bank-kw2", country="CH", default_currency="CHF"
    )
    acc = Account.objects.create(
        institution=bank, name="KW Test2", account_type="checking", currency="CHF"
    )
    acc.members.add(user)

    tx = Transaction.objects.create(
        account=acc,
        date=date(2026, 4, 1),
        amount=-10,
        display_name="ESSO STATION",
        description_raw="ESSO STATION",
        currency="CHF",
    )

    qs = Transaction.objects.filter(_keyword_q("ESSO"))
    assert tx in qs


# =============================================================================
# _generate_unique_slug
# =============================================================================


@pytest.mark.django_db
def test_generate_unique_slug_basic():
    from transactions.models import Category

    slug = _generate_unique_slug("Alimentation", Category)
    assert slug == "alimentation"


@pytest.mark.django_db
def test_generate_unique_slug_accents_stripped():
    from transactions.models import Category

    slug = _generate_unique_slug("Épargne & Retraite", Category)
    assert slug == "epargne_retraite"


@pytest.mark.django_db
def test_generate_unique_slug_hyphens_become_underscores():
    from transactions.models import Category

    slug = _generate_unique_slug("Vie courante", Category)
    assert "_" in slug
    assert "-" not in slug


@pytest.mark.django_db
def test_generate_unique_slug_collision_adds_suffix():
    from transactions.models import Category

    Category.objects.create(
        name="Collision", slug="collision", colour_hex="#aaa", order=1, is_system=False
    )
    slug = _generate_unique_slug("Collision", Category)
    assert slug == "collision_1"


@pytest.mark.django_db
def test_generate_unique_slug_double_collision():
    from transactions.models import Category

    Category.objects.create(
        name="Dbl", slug="dbl", colour_hex="#aaa", order=1, is_system=False
    )
    Category.objects.create(
        name="Dbl1", slug="dbl_1", colour_hex="#aaa", order=2, is_system=False
    )
    slug = _generate_unique_slug("Dbl", Category)
    assert slug == "dbl_2"


# =============================================================================
# _rgba
# =============================================================================


def test_rgba_basic():
    assert _rgba("#ff0000", 1.0) == "rgba(255,0,0,1.0)"


def test_rgba_black():
    assert _rgba("#000000", 0.5) == "rgba(0,0,0,0.5)"


def test_rgba_white():
    assert _rgba("#ffffff", 0.0) == "rgba(255,255,255,0.0)"


def test_rgba_strips_hash():
    assert _rgba("ff0000", 1.0) == "rgba(255,0,0,1.0)"


# =============================================================================
# _gradient
# =============================================================================


def test_gradient_structure():
    g = _gradient("#4ade80", 0.8, 0.1)
    assert g["type"] == "linear"
    assert len(g["colorStops"]) == 2
    assert g["colorStops"][0]["offset"] == 0
    assert g["colorStops"][1]["offset"] == 1


def test_gradient_none_color_fallback():
    g = _gradient(None, 0.8, 0.1)  # type: ignore[arg-type]
    assert "rgba" in g["colorStops"][0]["color"]


# =============================================================================
# _seg_factor
# =============================================================================


def test_seg_factor_single_segment():
    assert _seg_factor(0, 1) == 0.70


def test_seg_factor_first_of_many_is_brightest():
    assert _seg_factor(0, 5) == pytest.approx(0.70)


def test_seg_factor_last_of_many_is_darkest():
    assert _seg_factor(4, 5) == pytest.approx(0.35)


def test_seg_factor_range_valid():
    for i in range(10):
        f = _seg_factor(i, 10)
        assert 0.35 <= f <= 0.70


# =============================================================================
# _vary_color
# =============================================================================


def test_vary_color_full_factor():
    assert _vary_color("#ffffff", 1.0) == "#ffffff"


def test_vary_color_half_factor():
    # round(255 * 0.5) = 128 (arrondi bancaire Python), pas 127
    result = _vary_color("#ff0000", 0.5)
    assert result == "#800000"


def test_vary_color_none_fallback():
    result = _vary_color(None, 1.0)
    assert result == "#4ade80"


def test_vary_color_invalid_hex_fallback():
    result = _vary_color("#zzz", 1.0)
    assert result == "#4ade80"

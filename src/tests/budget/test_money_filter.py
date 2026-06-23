"""
tests/budget/test_money_filter.py — filtre `money` / `money_dec` (#118).

« La devise de partout » : un montant ne doit jamais s'afficher nu. Le filtre
formate le nombre (convention FR, comme |chf) ET y accole la devise fournie par le
site d'appel — point unique pour le futur toggle EUR/CHF.

On compose avec |chf / |chf_dec pour ne pas coder en dur le séparateur de milliers
(U+202F). Le séparateur nombre↔devise est un espace insécable (U+00A0).
"""

from decimal import Decimal

from transactions.templatetags.budget_filters import chf, chf_dec, money, money_dec

NBSP = "\xa0"  # espace insécable nombre↔devise (U+00A0)


def test_money_is_chf_format_plus_currency():
    assert money(1234, "EUR") == f"{chf(1234)}{NBSP}EUR"
    assert money(1234, "CHF") == f"{chf(1234)}{NBSP}CHF"


def test_money_dec_is_chf_dec_format_plus_currency():
    assert (
        money_dec(Decimal("1234.5"), "EUR") == f"{chf_dec(Decimal('1234.5'))}{NBSP}EUR"
    )


def test_money_defaults_to_chf():
    assert money(500) == f"500{NBSP}CHF"
    assert money_dec(Decimal("12.30")) == f"12,30{NBSP}CHF"


def test_money_uses_absolute_value_sign_handled_in_template():
    # Comme |chf : valeur absolue renvoyée, le signe (+/−) est ajouté côté template.
    assert money(-90, "CHF") == f"90{NBSP}CHF"
    assert money_dec(Decimal("-12.30"), "CHF") == f"12,30{NBSP}CHF"


def test_money_invalid_value_falls_back_gracefully():
    # _format_amount renvoie str(value) si non numérique → pas de crash, devise quand même.
    assert money("n/a", "CHF") == f"n/a{NBSP}CHF"

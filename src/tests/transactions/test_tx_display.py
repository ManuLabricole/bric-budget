"""
tests/transactions/test_tx_display.py — annotate_tx_display_icons (services/tx_display.py).

Bug réel corrigé (#124) : le badge logo marchand n'apparaissait QUE dans le panel
"Tout voir" (budget.views.transactions, seul appelant câblé à la main) — absent
partout où une AUTRE vue liste des transactions (zoom catégorie, zoom compte,
zoom classe d'actifs) car chacune ne posait que .institution_icon_url, jamais
.merchant_logo_url. Ce module remplace les 3 boucles dupliquées par UN point
unique — ces tests couvrent CE point, pas les 3 vues (dont les fragments
rendus sont couverts par leurs propres tests de vue).
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from tests.factories import AccountFactory, InstitutionFactory, TransactionFactory
from transactions.services import annotate_tx_display_icons, tx_display


@pytest.fixture
def account_with_icon(db):
    institution = InstitutionFactory(icon_slug="test-annotate-bank")
    return AccountFactory(institution=institution)


@override_settings(BRANDFETCH_CLIENT_ID="test-client-id")
@pytest.mark.django_db
def test_annotate_sets_both_institution_and_merchant_url(
    account_with_icon, monkeypatch
):
    monkeypatch.setattr(
        tx_display,
        "get_institution_icon_map",
        lambda: {"test-annotate-bank": "/static/icons/institutions/miniature/test.png"},
    )
    tx = TransactionFactory(account=account_with_icon, display_name="MIGROS LAUSANNE")

    result = annotate_tx_display_icons([tx])

    assert result[0] is tx
    assert tx.institution_icon_url == "/static/icons/institutions/miniature/test.png"
    assert tx.merchant_logo_url == (
        "https://cdn.brandfetch.io/domain/migros.ch/theme/light/w/48/h/48"
        "/fallback/404/icon.png?c=test-client-id"
    )


@pytest.mark.django_db
def test_annotate_sets_empty_institution_url_when_no_icon_slug(db):
    """Institution sans icon_slug → chaîne vide, pas de crash."""
    bare_institution = InstitutionFactory(icon_slug="")
    bare_account = AccountFactory(institution=bare_institution)
    tx = TransactionFactory(account=bare_account, display_name="GRENOBLE TABAC")

    result = annotate_tx_display_icons([tx])

    assert result[0].institution_icon_url == ""


@pytest.mark.django_db
def test_annotate_sets_empty_merchant_url_for_unknown_display_name(account_with_icon):
    tx = TransactionFactory(
        account=account_with_icon, display_name="GRENOBLE TABAC LE SAINT C"
    )
    result = annotate_tx_display_icons([tx])
    assert result[0].merchant_logo_url == ""


@override_settings(BRANDFETCH_CLIENT_ID="test-client-id")
@pytest.mark.django_db
def test_annotate_resolves_merchant_map_once_for_n_transactions(
    account_with_icon, monkeypatch
):
    """Pas de N+1 : get_merchant_logo_map appelé UNE fois pour toute la liste."""
    calls = {"n": 0}
    real_get_map = tx_display.get_merchant_logo_map

    def counting(names):
        calls["n"] += 1
        return real_get_map(names)

    monkeypatch.setattr(tx_display, "get_merchant_logo_map", counting)
    txs = [
        TransactionFactory(account=account_with_icon, display_name=f"SHOP {i}")
        for i in range(5)
    ]

    annotate_tx_display_icons(txs)

    assert calls["n"] == 1

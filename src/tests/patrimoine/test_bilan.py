"""
tests/patrimoine/test_bilan.py — arbre bilan (BilanNode) (TDD).

overview_bilan reçoit des comptes DÉJÀ scopés for_user et construit l'arbre
AssetClass → comptes (value/share/delta/url). delta=None (SOON liquidités).
"""

import datetime
from decimal import Decimal

import pytest

from patrimoine.services.bilan import BilanNode, overview_bilan


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


def _node(nodes, label):
    return next(n for n in nodes if n.label == label)


@pytest.mark.django_db
def test_overview_groups_by_asset_class_with_values(
    chf_account, savings_account, make_snapshot, user
):
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    make_snapshot(savings_account, "2026-03-10", balance=500, balance_chf=500)
    nodes = overview_bilan([chf_account, savings_account], on=_d("2026-03-10"))

    cc = _node(nodes, "Comptes courants")
    liv = _node(nodes, "Livrets")
    assert cc.value == Decimal("1000")
    assert liv.value == Decimal("500")
    # Parts du grand total (1500) — somme ~100.
    assert cc.share == Decimal("66.67")
    assert liv.share == Decimal("33.33")
    # delta = SOON pour le cash.
    assert cc.delta is None
    # Le label est un lien vers la page classe.
    assert cc.url.endswith("/patrimoine/comptes-courants/")
    # Enfants = comptes.
    assert [c.label for c in cc.children] == ["CHF Courant"]
    assert cc.children[0].value == Decimal("1000")


@pytest.mark.django_db
def test_non_functional_class_is_soon(chf_account, make_snapshot):
    make_snapshot(chf_account, "2026-03-10", balance=1000, balance_chf=1000)
    nodes = overview_bilan([chf_account], on=_d("2026-03-10"))
    crypto = _node(nodes, "Crypto")
    assert crypto.soon is True
    assert crypto.value is None
    assert crypto.share is None


@pytest.mark.django_db
def test_account_without_anchor_has_unknown_value(chf_account, make_tx):
    """Compte sans snapshot (ex. Yuh 0 snap) → valeur inconnue (None), pas un 0 inventé."""
    make_tx(chf_account, "2026-03-11", 100, amount_chf=100)
    nodes = overview_bilan([chf_account], on=_d("2026-03-12"))
    cc = _node(nodes, "Comptes courants")
    assert cc.children[0].value is None


def test_bilan_node_defaults():
    n = BilanNode(label="x", color="#fff", value=Decimal("1"))
    assert n.share is None and n.delta is None and n.soon is False and n.children == []

"""
tests/patrimoine/test_asset_classes.py — registre des classes d'actifs.

Tests purs (pas de DB) : le registre est un mapping statique Python.
"""

from patrimoine.services.asset_classes import (
    ASSET_CLASSES,
    AssetClass,
    get_asset_class,
)


def test_get_known_slug_returns_asset_class():
    ac = get_asset_class("comptes-courants")
    assert isinstance(ac, AssetClass)
    assert ac.label == "Comptes courants"
    assert ac.functional is True


def test_get_unknown_slug_returns_none():
    assert get_asset_class("xxx-inexistant") is None


def test_slugs_are_unique():
    slugs = [ac.slug for ac in ASSET_CLASSES]
    assert len(slugs) == len(set(slugs))


def test_every_asset_class_is_complete():
    """Chaque classe a un slug, un label et au moins un account_type rattaché."""
    for ac in ASSET_CLASSES:
        assert ac.slug
        assert ac.label
        assert ac.account_types  # tuple non vide


def test_every_asset_class_has_a_hex_color():
    """Couleur = source de vérité (donut/courbe/pastille) — token hex valide, unique par classe."""
    import re

    colors = [ac.color for ac in ASSET_CLASSES]
    for c in colors:
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", c), f"couleur invalide : {c}"
    assert len(colors) == len(set(colors)), "couleurs non uniques"


def test_functional_classes_are_liquidity_only():
    """En Phase 3A, seules les liquidités (checking/savings) sont fonctionnelles."""
    functional = {ac.slug for ac in ASSET_CLASSES if ac.functional}
    assert functional == {"comptes-courants", "livrets"}


def test_asset_class_is_immutable():
    """frozen=True → on ne peut pas muter le registre par accident."""
    ac = get_asset_class("livrets")
    assert ac is not None
    import dataclasses

    try:
        ac.label = "Hacked"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("AssetClass devrait être immuable (frozen=True)")

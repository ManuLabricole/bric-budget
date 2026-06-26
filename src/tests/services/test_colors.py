"""
tests/services/test_colors.py — palette dérivée + règle d'allocation (#134).

Tests purs (pas de DB) : palette = données Python, allocation = fonction pure.

Couvre :
  - validité de la palette (hex, unicité, taille des tiers) ;
  - allocation : ordre PRIMARY → LIGHT → DARK, stabilité, insensibilité à la casse,
    épuisement cyclique ;
  - synchro du fichier généré avec le générateur (même garde que tailwind.config).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from services.colors import (
    allocate_color,
    is_palette_color,
    palette_dict,
)
from services.palette import DARK, LIGHT, PALETTE, PRIMARY

_HEX = re.compile(r"#[0-9a-f]{6}")


# =============================================================================
# Validité de la palette
# =============================================================================


def test_every_tier_has_16_colors():
    """Une dérivée light + une dark par teinte catégorie (16)."""
    assert len(PRIMARY) == 16
    assert len(LIGHT) == 16
    assert len(DARK) == 16


def test_palette_is_concatenation_of_tiers_in_order():
    """PALETTE = PRIMARY puis LIGHT puis DARK — l'ordre porte la règle d'allocation."""
    assert PALETTE == PRIMARY + LIGHT + DARK
    assert len(PALETTE) == 48


def test_all_colors_are_valid_lowercase_hex():
    for colour in PALETTE:
        assert _HEX.fullmatch(colour), f"hex invalide : {colour}"


def test_all_palette_colors_are_unique():
    """Pas de doublon : 48 couleurs distinctes (sinon l'allocation 'saute' une teinte)."""
    assert len(PALETTE) == len(set(PALETTE))


def test_primary_matches_category_palette_source():
    """Le tier PRIMARY EST la palette catégories (source de vérité commune)."""
    from budget.constants import CATEGORY_COLOR_PALETTE

    assert list(PRIMARY) == [c["hex"] for c in CATEGORY_COLOR_PALETTE]


# =============================================================================
# Règle d'allocation
# =============================================================================


def test_first_allocation_is_first_primary():
    """Rien de pris → on donne la 1re couleur PRIMARY."""
    assert allocate_color([]) == PRIMARY[0]


def test_allocation_walks_through_primary_first():
    """On épuise tout PRIMARY avant de toucher LIGHT."""
    used: list[str] = []
    for expected in PRIMARY:
        got = allocate_color(used)
        assert got == expected
        used.append(got)
    # Le 17e doit basculer sur le premier LIGHT.
    assert allocate_color(used) == LIGHT[0]


def test_allocation_reaches_dark_after_light():
    """Les 32 premières (primary+light) prises → on entre dans DARK."""
    used = list(PRIMARY) + list(LIGHT)
    assert allocate_color(used) == DARK[0]


def test_allocation_is_stable_skips_only_taken():
    """On rend la 1re LIBRE : si un trou existe au milieu, on le comble."""
    used = [PRIMARY[0], PRIMARY[2]]  # PRIMARY[1] libre
    assert allocate_color(used) == PRIMARY[1]


def test_allocation_is_case_insensitive():
    """Un hex stocké en MAJUSCULES est reconnu comme pris."""
    used = [PRIMARY[0].upper()]
    got = allocate_color(used)
    assert got == PRIMARY[1]
    assert got != PRIMARY[0]


def test_allocation_ignores_empty_and_non_palette_values():
    """colour_hex vide / hors palette ne bloque pas l'allocation des tiers."""
    used = ["", "#000000", "  "]
    assert allocate_color(used) == PRIMARY[0]


def test_allocation_is_cyclic_when_all_taken():
    """> 48 entités : on boucle sur PALETTE (déterministe, jamais None)."""
    used = list(PALETTE)
    got = allocate_color(used)
    assert got in PALETTE  # pas None, pas d'exception
    assert got == PALETTE[len(used) % len(PALETTE)]


def test_allocation_never_returns_empty():
    assert allocate_color(list(PALETTE) * 3)  # tier épuisé plusieurs fois


# =============================================================================
# Lookup + exposition tokens
# =============================================================================


def test_is_palette_color_true_for_member():
    assert is_palette_color(PRIMARY[0]) is True
    assert is_palette_color(PRIMARY[0].upper()) is True


def test_is_palette_color_false_for_outsider():
    assert is_palette_color("#123456") is False


def test_palette_dict_shape_for_tokens():
    """Format exposé à BRICBUDGET_TOKENS.palette : un tableau par tier."""
    d = palette_dict()
    assert set(d.keys()) == {"primary", "light", "dark"}
    assert d["primary"] == list(PRIMARY)
    assert d["light"] == list(LIGHT)
    assert d["dark"] == list(DARK)


# =============================================================================
# Synchro fichier généré ↔ générateur (même garde que tailwind.config / tokens.js)
# =============================================================================


def test_palette_is_in_sync():
    """`python scripts/gen_palette.py --check` doit passer (palette.py à jour)."""
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "gen_palette.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "services/palette.py est périmé — relance `python scripts/gen_palette.py`.\n"
        f"stderr: {result.stderr}"
    )

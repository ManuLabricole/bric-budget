"""
services/palette.py — palette dérivée committée (#134). GÉNÉRÉ, NE PAS ÉDITER À LA MAIN.

Régénérer : `python scripts/gen_palette.py` (le test `test_palette_is_in_sync`
échoue si ce fichier n'est plus synchro avec le générateur).

Trois tiers, dans l'ordre d'allocation (cf. services/colors.py) :
  PRIMARY → les 16 teintes catégories (source de vérité, harmonisées au thème) ;
  LIGHT   → variante +lightness de chaque teinte ;
  DARK    → variante -lightness de chaque teinte.

Total : 48 couleurs déterministes. Allouées une fois et stockées
en DB par entité (compte, institution, position) → stables à vie.
"""

from __future__ import annotations

# fmt: off
PRIMARY: tuple[str, ...] = (
    "#eed8b4",
    "#deab5e",
    "#e77f79",
    "#5abdc5",
    "#63e096",
    "#b09be8",
    "#f09e5a",
    "#7ec8e3",
    "#f0c878",
    "#e8a0b0",
    "#95d4b4",
    "#d4a0d0",
    "#c8d87c",
    "#a0c8f8",
    "#98d8d8",
    "#e8c8a8",
)

LIGHT: tuple[str, ...] = (
    "#f4e6ce",
    "#eac896",
    "#efaca8",
    "#94d4d9",
    "#9aebbb",
    "#ccbef0",
    "#f5c094",
    "#abdbed",
    "#f5dba7",
    "#f0c1cc",
    "#bae3ce",
    "#e3c1e0",
    "#dbe6aa",
    "#c1dbfa",
    "#bce6e6",
    "#f0dbc6",
)

DARK: tuple[str, ...] = (
    "#d19533",
    "#a36f21",
    "#b92921",
    "#2e7d84",
    "#21a758",
    "#562dc3",
    "#bc5e11",
    "#278eb4",
    "#c98d16",
    "#c42f50",
    "#419f6f",
    "#9f4898",
    "#8fa230",
    "#1175ec",
    "#3fa5a5",
    "#c47c34",
)
# fmt: on

# Ordre d'allocation : on épuise PRIMARY, puis LIGHT, puis DARK.
PALETTE: tuple[str, ...] = PRIMARY + LIGHT + DARK

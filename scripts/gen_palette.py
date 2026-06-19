#!/usr/bin/env python3
"""
scripts/gen_palette.py — génère la palette dérivée committée (#134).

POURQUOI un script run-once plutôt qu'un calcul au rendu :
  - déterministe et auditable : le diff git montre exactement les 48 couleurs ;
  - zéro calcul HSL à chaque requête / chaque rendu de chart ;
  - une seule source de vérité (les 16 teintes catégories) → les dérivées en
    découlent mécaniquement, jamais réglées à la main.

Tiers produits (dans l'ordre d'allocation primary → light → dark) :
  - PRIMARY : les 16 teintes catégories telles quelles (déjà harmonisées au thème) ;
  - LIGHT   : variante +lightness de chaque teinte (HSL, L *= LIGHT_FACTOR vers le blanc) ;
  - DARK    : variante -lightness de chaque teinte (HSL, L *= DARK_FACTOR vers le noir).

Usage :
    python scripts/gen_palette.py            # écrit src/services/palette.py
    python scripts/gen_palette.py --check     # n'écrit pas, sort 1 si le fichier est périmé

Le test pytest `test_palette_is_in_sync` rejoue ce générateur et compare au fichier
committé — même garde que la synchro tailwind.config / tokens.js.
"""

from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path

# Source de vérité : les 16 teintes catégories. On les redéfinit ici (et pas
# d'import budget.constants) pour que le générateur reste un script autonome,
# exécutable sans Django configuré. Le test de synchro garde les deux alignés.
PRIMARY_HEXES: tuple[str, ...] = (
    "#eed8b4",  # Ocre
    "#deab5e",  # Caramel
    "#e77f79",  # Corail
    "#5abdc5",  # Cyan
    "#63e096",  # Menthe
    "#b09be8",  # Lavande
    "#f09e5a",  # Orange
    "#7ec8e3",  # Ciel
    "#f0c878",  # Miel
    "#e8a0b0",  # Rose
    "#95d4b4",  # Sauge
    "#d4a0d0",  # Lilas
    "#c8d87c",  # Citron
    "#a0c8f8",  # Bleu
    "#98d8d8",  # Turquoise
    "#e8c8a8",  # Sable
)

# Facteurs de luminosité HSL. Choisis pour rester lisibles sur fond #131314 :
#   light → on rapproche L du blanc (1.0) de 35 % ;
#   dark  → on rapproche L du noir (0.0) à 62 % de la valeur d'origine.
LIGHT_FACTOR = 0.35  # part du chemin restant vers L=1.0
DARK_FACTOR = 0.62  # L *= ce facteur

_OUTPUT = Path(__file__).resolve().parent.parent / "src" / "services" / "palette.py"


def _hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def lighten(hex_str: str, factor: float = LIGHT_FACTOR) -> str:
    """Éclaircit une couleur : L parcourt `factor` du chemin restant vers le blanc."""
    r, g, b = _hex_to_rgb(hex_str)
    h, ligh, s = colorsys.rgb_to_hls(r, g, b)
    ligh = ligh + (1.0 - ligh) * factor
    return _rgb_to_hex(colorsys.hls_to_rgb(h, ligh, s))


def darken(hex_str: str, factor: float = DARK_FACTOR) -> str:
    """Assombrit une couleur : L est multipliée par `factor` (vers le noir)."""
    r, g, b = _hex_to_rgb(hex_str)
    h, ligh, s = colorsys.rgb_to_hls(r, g, b)
    ligh = ligh * factor
    return _rgb_to_hex(colorsys.hls_to_rgb(h, ligh, s))


def build_module_source() -> str:
    """Rend le contenu complet de src/services/palette.py."""
    light = [lighten(h) for h in PRIMARY_HEXES]
    dark = [darken(h) for h in PRIMARY_HEXES]

    def _fmt(seq: tuple[str, ...] | list[str]) -> str:
        return "\n".join(f'    "{h}",' for h in seq)

    return f'''"""
services/palette.py — palette dérivée committée (#134). GÉNÉRÉ, NE PAS ÉDITER À LA MAIN.

Régénérer : `python scripts/gen_palette.py` (le test `test_palette_is_in_sync`
échoue si ce fichier n'est plus synchro avec le générateur).

Trois tiers, dans l'ordre d'allocation (cf. services/colors.py) :
  PRIMARY → les 16 teintes catégories (source de vérité, harmonisées au thème) ;
  LIGHT   → variante +lightness de chaque teinte ;
  DARK    → variante -lightness de chaque teinte.

Total : {len(PRIMARY_HEXES) * 3} couleurs déterministes. Allouées une fois et stockées
en DB par entité (compte, institution, position) → stables à vie.
"""

from __future__ import annotations

# fmt: off
PRIMARY: tuple[str, ...] = (
{_fmt(PRIMARY_HEXES)}
)

LIGHT: tuple[str, ...] = (
{_fmt(light)}
)

DARK: tuple[str, ...] = (
{_fmt(dark)}
)
# fmt: on

# Ordre d'allocation : on épuise PRIMARY, puis LIGHT, puis DARK.
PALETTE: tuple[str, ...] = PRIMARY + LIGHT + DARK
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Génère src/services/palette.py")
    parser.add_argument(
        "--check",
        action="store_true",
        help="N'écrit pas ; sort 1 si le fichier committé est périmé.",
    )
    args = parser.parse_args()

    source = build_module_source()

    if args.check:
        current = _OUTPUT.read_text() if _OUTPUT.exists() else ""
        if current != source:
            sys.stderr.write(f"PÉRIMÉ : {_OUTPUT} ne correspond pas au générateur.\n")
            return 1
        sys.stdout.write("OK : palette.py synchro.\n")
        return 0

    _OUTPUT.write_text(source)
    sys.stdout.write(f"Écrit {_OUTPUT} ({len(source.splitlines())} lignes).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

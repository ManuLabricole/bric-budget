"""
services/colors.py — allocation et lookup de couleurs de la palette (#134).

Point d'accès UNIQUE de la palette pour le code Python. Les modèles (compte,
institution, position) appellent `allocate_color(...)` à la CRÉATION pour obtenir
une couleur stable, puis la stockent en DB (pattern `Category.colour_hex`). Une
fois stockée, elle ne bouge plus, même si la liste d'entités grandit.

POURQUOI une fonction pure (et pas un manager couplé aux modèles) :
  - réutilisable par n'importe quelle app (accounts, patrimoine) sans import croisé ;
  - testable sans DB (on lui passe la liste des hex déjà pris) ;
  - c'est la « couture » que les vues de création #137 / #82 brancheront — ici on
    livre le mécanisme, pas le câblage modèle (champ DB + migration = côté modèles).

Règle d'allocation : prochaine couleur LIBRE en parcourant PRIMARY → LIGHT → DARK.
Si tout est pris (> 48 entités colorées du même domaine), on boucle sur PALETTE
en repartant du début — la collision est alors assumée et déterministe plutôt
que de renvoyer None et casser une création.
"""

from __future__ import annotations

from collections.abc import Iterable

from services.palette import DARK, LIGHT, PALETTE, PRIMARY

__all__ = [
    "PALETTE",
    "PRIMARY",
    "LIGHT",
    "DARK",
    "allocate_color",
    "palette_dict",
    "is_palette_color",
]


def _normalize(hex_str: str) -> str:
    """Minuscule + préfixe # — pour comparer des hex saisis de façons variées."""
    h = hex_str.strip().lower()
    return h if h.startswith("#") else f"#{h}"


def allocate_color(used: Iterable[str]) -> str:
    """
    Retourne la prochaine couleur libre de la palette (PRIMARY → LIGHT → DARK).

    `used` = les hex DÉJÀ attribués dans le domaine considéré (ex. tous les
    `Account.colour_hex` non vides). Comparaison insensible à la casse.

    Épuisement : si les 48 couleurs sont prises, on recommence au début de
    PALETTE (allocation cyclique) — déterministe, jamais None.
    """
    taken = {_normalize(h) for h in used if h}
    for colour in PALETTE:
        if colour not in taken:
            return colour
    # Tous les tiers épuisés → on boucle. len(taken) compte les attributions ;
    # le modulo donne un point de reprise stable dans la palette.
    return PALETTE[len(taken) % len(PALETTE)]


def is_palette_color(hex_str: str) -> bool:
    """Vrai si `hex_str` (insensible à la casse) appartient à la palette."""
    return _normalize(hex_str) in set(PALETTE)


def palette_dict() -> dict[str, list[str]]:
    """
    Palette structurée par tier — pour exposition à `BRICBUDGET_TOKENS.palette`.

    Format : {"primary": [...], "light": [...], "dark": [...]}. Les charts JS lisent
    ces tiers au lieu de hardcoder des hex (règle existante : zéro hex inline en JS).
    """
    return {
        "primary": list(PRIMARY),
        "light": list(LIGHT),
        "dark": list(DARK),
    }

"""
budget/context_processors.py — Données globales injectées dans tous les templates.

Ajouté à TEMPLATES.OPTIONS.context_processors dans config/settings.py.
Évite à chaque vue de re-passer les mêmes constantes au template.
"""

import json

from budget.constants import CATEGORY_COLOR_PALETTE
from services.colors import palette_dict as derived_palette_dict


def design_tokens(request):
    """
    Expose les couleurs Python dans `window.BRICBUDGET_TOKENS` (charts, picker).

    Pourquoi : les scripts JS utilisent les couleurs sans dupliquer les listes dans
    `static/js/`. Source de vérité unique en Python. Règle existante : zéro hex inline en JS.

    Deux clés injectées dans base.html :
      - `category_palette_json` → `.categories` : {"ocre": "#eed8b4", ...} (catégories budget) ;
      - `derived_palette_json`  → `.palette`    : {"primary": [...], "light": [...], "dark": [...]}
        (palette dérivée #134 — tiers d'allocation pour comptes / institutions / positions).
    """
    palette_dict = {c["name"].lower(): c["hex"] for c in CATEGORY_COLOR_PALETTE}
    return {
        "category_palette_json": json.dumps(palette_dict),
        "derived_palette_json": json.dumps(derived_palette_dict()),
    }

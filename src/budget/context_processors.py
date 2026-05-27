"""
budget/context_processors.py — Données globales injectées dans tous les templates.

Ajouté à TEMPLATES.OPTIONS.context_processors dans config/settings.py.
Évite à chaque vue de re-passer les mêmes constantes au template.
"""

import json

from budget.constants import CATEGORY_COLOR_PALETTE


def design_tokens(request):
    """
    Expose la palette catégories en JSON pour injection dans `window.BRICBUDGET_TOKENS.categories`.

    Pourquoi : permet aux scripts JS (charts, picker) d'utiliser les couleurs par défaut
    de la palette sans dupliquer la liste dans `static/js/`. Source de vérité unique en Python.

    Format : {"ocre": "#eed8b4", "caramel": "#deab5e", ...}
    """
    palette_dict = {c["name"].lower(): c["hex"] for c in CATEGORY_COLOR_PALETTE}
    return {"category_palette_json": json.dumps(palette_dict)}

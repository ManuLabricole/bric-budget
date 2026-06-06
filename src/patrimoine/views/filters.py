"""
patrimoine/views/filters.py — état du filtre par classe d'actifs (session).

Le filtre sélectionne quelles classes d'actifs apparaissent dans la courbe, la table et
le donut de l'overview. La VUE toggle_class vit dans overview.py (réponse HTMX/redirect) ;
ici uniquement l'état (clé session + helpers), sans dépendance circulaire.
"""

from __future__ import annotations

from patrimoine.services.asset_classes import ASSET_CLASSES

FILTER_SESSION_KEY = "patrimoine_selected_classes"


def _all_slugs() -> list[str]:
    return [ac.slug for ac in ASSET_CLASSES]


def selected_class_slugs(session) -> list[str]:
    """Slugs des classes sélectionnées (défaut : toutes). Ordre du registre conservé."""
    selected = set(session.get(FILTER_SESSION_KEY, _all_slugs()))
    return [s for s in _all_slugs() if s in selected]

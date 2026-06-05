"""
patrimoine/views/filters.py — filtre par classe d'actifs (état session, PRG).

Le filtre sélectionne quelles classes d'actifs apparaissent dans la courbe, la table
et le donut de l'overview. État = liste de slugs sélectionnés en session.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from patrimoine.services.asset_classes import ASSET_CLASSES, get_asset_class

FILTER_SESSION_KEY = "patrimoine_selected_classes"


def _all_slugs() -> list[str]:
    return [ac.slug for ac in ASSET_CLASSES]


def selected_class_slugs(session) -> list[str]:
    """Slugs des classes sélectionnées (défaut : toutes). Ordre du registre conservé."""
    selected = set(session.get(FILTER_SESSION_KEY, _all_slugs()))
    return [s for s in _all_slugs() if s in selected]


@require_POST
@login_required
def toggle_class(request, slug: str):
    """Coche/décoche une classe d'actifs dans le filtre. `slug == "all"` → tout cocher."""
    if slug == "all":
        request.session[FILTER_SESSION_KEY] = _all_slugs()
        return redirect("patrimoine:overview")

    if get_asset_class(slug) is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")

    selected = set(selected_class_slugs(request.session))
    selected.discard(slug) if slug in selected else selected.add(slug)
    request.session[FILTER_SESSION_KEY] = [s for s in _all_slugs() if s in selected]
    return redirect("patrimoine:overview")

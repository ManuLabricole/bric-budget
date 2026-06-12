"""
transactions/templatetags/institution_icons.py

Template tag pour résoudre l'URL statique d'un logo institution.

Usage dans un template :

    {% load institution_icons %}

    {# Résolution directe #}
    {% institution_icon_url institution %}

    {# Stocker dans une variable (nécessaire pour passer à un include) #}
    {% institution_icon_url institution as icon_url %}
    {% include "components/institutions/institution_logo.html" with icon_url=icon_url institution=institution %}

Pourquoi ce tag existe
----------------------
Les logos institution peuvent être SVG (priorité, fond transparent, currentColor)
ou PNG miniature (fallback, fond blanc). La logique de résolution SVG→PNG
est ici centralisée pour tout template.

La vue budget/views.py utilise son propre _resolve_institution_icon_map() pour
résoudre en lot (1 scan disque → dict, O(1) par transaction). Ce tag est
destiné aux templates où le volume est faible (< 10 institutions) et où passer
institution_icon_url depuis Python serait inutilement verbeux.

Ajouter un nouveau logo institution
-----------------------------------
→ Déposer le SVG dans  static/icons/institutions/svg/<slug>.svg
→ Le nom du fichier doit correspondre à Institution.icon_slug (ou Institution.slug si vide)
→ Le SVG doit utiliser fill="currentColor" — pas de fill="#xxx" hardcodé
→ Pas de rect/fond blanc intégré (supprimer dans Inkscape si besoin)
→ Le PNG miniature dans static/icons/institutions/miniature/<slug>.png sert de fallback
"""

from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


def _resolve_icon_url(slug: str) -> str:
    """
    SVG si disponible dans static/icons/institutions/svg/, sinon PNG/JPG miniature,
    sinon chaîne vide (le composant institution_logo affiche alors une initiale).
    """
    base = Path(settings.BASE_DIR) / "static" / "icons" / "institutions"

    svg = base / "svg" / f"{slug}.svg"
    if svg.is_file():
        return static(f"icons/institutions/svg/{slug}.svg")

    for ext in ("png", "jpg", "jpeg"):
        fallback = base / "miniature" / f"{slug}.{ext}"
        if fallback.is_file():
            return static(f"icons/institutions/miniature/{slug}.{ext}")

    return ""


@register.simple_tag
def institution_icon_url(institution_or_slug) -> str:
    """
    Retourne l'URL statique du logo pour une institution.

    Accepte :
        - un objet Institution Django (lit .icon_slug, fallback sur .slug)
        - une chaîne slug directement ("yuh", "ubs", "cic"…)
    """
    if hasattr(institution_or_slug, "icon_slug"):
        slug = institution_or_slug.icon_slug or getattr(institution_or_slug, "slug", "")
    elif hasattr(institution_or_slug, "slug"):
        slug = institution_or_slug.slug
    else:
        slug = str(institution_or_slug)

    return _resolve_icon_url(slug)

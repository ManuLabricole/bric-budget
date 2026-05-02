"""
transactions/templatetags/bank_icons.py

Template tag pour résoudre l'URL statique d'un logo banque.

Usage dans un template :

    {% load bank_icons %}

    {# Résolution directe #}
    {% bank_icon_url bank %}

    {# Stocker dans une variable (nécessaire pour passer à un include) #}
    {% bank_icon_url bank as icon_url %}
    {% include "components/banks/bank_logo.html" with icon_url=icon_url bank=bank %}

Pourquoi ce tag existe
----------------------
Les logos banque peuvent être SVG (priorité, fond transparent, currentColor)
ou PNG miniature (fallback, fond blanc). La logique de résolution SVG→PNG
est ici centralisée pour tout template.

La vue budget/views.py utilise son propre _resolve_bank_icon_map() pour
résoudre en lot (1 scan disque → dict, O(1) par transaction). Ce tag est
destiné aux templates où le volume est faible (< 10 banques) et où passer
bank_icon_url depuis Python serait inutilement verbeux.

Ajouter un nouveau logo banque
--------------------------------
→ Déposer le SVG dans  static/icons/banks/svg/<slug>.svg
→ Le nom du fichier doit correspondre à Bank.icon_slug (ou Bank.slug si vide)
→ Le SVG doit utiliser fill="currentColor" — pas de fill="#xxx" hardcodé
→ Pas de rect/fond blanc intégré (supprimer dans Inkscape si besoin)
→ Le PNG miniature dans static/icons/banks/miniature/<slug>.png sert de fallback
"""

from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


def _resolve_icon_url(slug: str) -> str:
    """
    SVG si disponible dans static/icons/banks/svg/, sinon PNG/JPG miniature,
    sinon chaîne vide (le composant bank_logo affiche alors une initiale).
    """
    base = Path(settings.BASE_DIR) / "static" / "icons" / "banks"

    svg = base / "svg" / f"{slug}.svg"
    if svg.is_file():
        return static(f"icons/banks/svg/{slug}.svg")

    for ext in ("png", "jpg", "jpeg"):
        fallback = base / "miniature" / f"{slug}.{ext}"
        if fallback.is_file():
            return static(f"icons/banks/miniature/{slug}.{ext}")

    return ""


@register.simple_tag
def bank_icon_url(bank_or_slug) -> str:
    """
    Retourne l'URL statique du logo pour une banque.

    Accepte :
        - un objet Bank Django (lit .icon_slug, fallback sur .slug)
        - une chaîne slug directement ("yuh", "ubs", "cic"…)
    """
    if hasattr(bank_or_slug, "icon_slug"):
        slug = bank_or_slug.icon_slug or getattr(bank_or_slug, "slug", "")
    elif hasattr(bank_or_slug, "slug"):
        slug = bank_or_slug.slug
    else:
        slug = str(bank_or_slug)

    return _resolve_icon_url(slug)

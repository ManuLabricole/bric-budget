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

Thin wrapper (#139)
-------------------
La résolution SVG→PNG est centralisée dans services.logos (source unique, partagée
par les templates ET les vues). Ce tag délègue : il ne fait QUE l'exposer aux
templates. Côté Python, appeler directement services.logos.institution_icon_url.

Ajouter un nouveau logo institution
-----------------------------------
→ Déposer le SVG dans  static/icons/institutions/svg/<slug>.svg
→ Le nom du fichier doit correspondre à Institution.icon_slug (ou Institution.slug si vide)
→ Le SVG doit utiliser fill="currentColor" — pas de fill="#xxx" hardcodé
→ Pas de rect/fond blanc intégré (supprimer dans Inkscape si besoin)
→ Le PNG miniature dans static/icons/institutions/miniature/<slug>.png sert de fallback
"""

from django import template

register = template.Library()


@register.simple_tag(name="institution_icon_url")
def institution_icon_url_tag(institution_or_slug) -> str:
    """Expose services.logos.institution_icon_url aux templates (objet ou slug → URL)."""
    from services.logos import institution_icon_url

    return institution_icon_url(institution_or_slug)

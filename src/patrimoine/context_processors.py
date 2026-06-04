"""
patrimoine/context_processors.py — injecte la navigation patrimoine dans TOUS les templates.

La sidebar (`Patrimoine ▼`) vit dans base_app.html, rendu pour toutes les pages
(budget, imports…). Elle a donc besoin du registre des classes d'actifs et de l'état
ouvert/fermé partout, pas seulement sur les vues patrimoine.

Ajouté à TEMPLATES.OPTIONS.context_processors dans config/settings.py.
"""

from __future__ import annotations

from patrimoine.services.asset_classes import ASSET_CLASSES

# Clé de session qui mémorise si le disclosure « Patrimoine » est déplié.
SIDEBAR_SESSION_KEY = "patrimoine_sidebar_open"


def sidebar(request):
    """
    Expose au template :
      - asset_classes          : registre complet (sous-items de la sidebar)
      - patrimoine_sidebar_open: bool — état déplié, persisté en session
      - active_asset_class_slug: slug de la classe courante (surbrillance), ou None
    """
    # Slug actif : déduit de l'URL résolue (kwarg `slug` des vues patrimoine).
    # resolver_match est None sur certaines réponses (404 avant résolution) → garde.
    active_slug = None
    match = request.resolver_match
    if match is not None and match.app_name == "patrimoine":
        active_slug = match.kwargs.get("slug")

    return {
        "asset_classes": ASSET_CLASSES,
        "patrimoine_sidebar_open": request.session.get(SIDEBAR_SESSION_KEY, False),
        "active_asset_class_slug": active_slug,
    }

"""
patrimoine/views/navigation.py — sidebar toggle patrimoine (PR A).

sidebar_toggle : persiste l'état déplié/replié du disclosure « Patrimoine ».
asset_class_page est dans views/asset_class.py.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from patrimoine.context_processors import SIDEBAR_SESSION_KEY

logger = logging.getLogger(__name__)


@require_POST
@login_required
def sidebar_toggle(request):
    """
    Persiste l'état déplié/replié de la section « Patrimoine » en session.

    Le visuel (chevron + accordéon) est piloté en CSS pur côté template (checkbox +
    group-has-[:checked]) → ce POST est un simple fire-and-forget (hx-swap="none") qui
    ne renvoie rien à afficher. On lit l'état RÉEL de la checkbox (`open` présent =
    cochée) plutôt que d'inverser, pour rester synchrone avec le client sans risque de
    désync. Réponse 204 : aucun contenu à échanger.
    """
    is_open = "open" in request.POST
    request.session[SIDEBAR_SESSION_KEY] = is_open
    logger.debug("patrimoine_sidebar_toggle user=%s open=%s", request.user.id, is_open)
    return HttpResponse(status=204)

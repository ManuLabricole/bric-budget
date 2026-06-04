"""
patrimoine/views/navigation.py — coquille navigable du patrimoine (PR A).

Deux vues :
  - asset_class_page : page d'une classe d'actifs (listing comptes si fonctionnelle,
    état SOON sinon). Pas de graphe / panneau / soldes → ça vient en PR B/C.
  - sidebar_toggle   : persiste l'état déplié/replié du disclosure « Patrimoine ».

Sécurité : listing scopé utilisateur via Account.objects.for_user (SR-001 / IDOR).
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.models import Account
from patrimoine.context_processors import SIDEBAR_SESSION_KEY
from patrimoine.services.asset_classes import get_asset_class


@login_required
def asset_class_page(request, slug: str):
    """Page d'une classe d'actifs. 404 si slug inconnu ; état SOON si non fonctionnelle."""
    asset_class = get_asset_class(slug)
    if asset_class is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")

    if not asset_class.functional:
        # Catégorie pas encore prête → page SOON, jamais de 404 (cf. rules/ui-layout).
        return render(
            request,
            "patrimoine/asset_class_soon.html",
            {"asset_class": asset_class},
        )

    # IDOR : on ne liste QUE les comptes dont l'utilisateur est membre (SR-001).
    # for_user filtre déjà sur members ; on restreint en plus aux comptes actifs
    # et aux account_types de la classe. select_related évite le N+1 sur institution
    # (utilisée par le {% regroup %} du template).
    accounts = (
        Account.objects.for_user(request.user)
        .filter(is_active=True, account_type__in=asset_class.account_types)
        .select_related("institution")
        .order_by("institution__name", "name")
    )

    return render(
        request,
        "patrimoine/asset_class.html",
        {"asset_class": asset_class, "accounts": accounts},
    )


@require_POST
@login_required
def sidebar_toggle(request):
    """
    Bascule l'état déplié/replié du disclosure « Patrimoine » en session.

    Câblé sur l'événement `toggle` du <details> côté template : chaque ouverture/
    fermeture émet un POST, on inverse le booléen. L'initial render reflète la session,
    donc un toggle = un changement d'état → reste synchrone. `hx-swap="none"` côté client.
    """
    request.session[SIDEBAR_SESSION_KEY] = not request.session.get(
        SIDEBAR_SESSION_KEY, False
    )
    # 204 : rien à réafficher (l'état visuel est déjà géré nativement par <details>).
    return HttpResponse(status=204)

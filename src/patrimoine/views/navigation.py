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
def overview(request):
    """
    Page bilan patrimoine (« Patrimoine brut ») — cible du clic sur le label « Patrimoine ».

    Placeholder en Phase 3A : le bilan complet (net worth consolidé, performance,
    table actifs, donut) dépend de la valorisation des investissements (v0.5→v0.8).
    Atterrir ici déplie la section dans la sidebar.
    """
    request.session[SIDEBAR_SESSION_KEY] = True
    return render(request, "patrimoine/overview_soon.html")


@login_required
def asset_class_page(request, slug: str):
    """Page d'une classe d'actifs. 404 si slug inconnu ; état SOON si non fonctionnelle."""
    asset_class = get_asset_class(slug)
    if asset_class is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")

    # Être sur une page classe d'actifs implique que la section est dépliée
    # (on y accède en cliquant un sous-item) → garder la sidebar cohérente.
    request.session[SIDEBAR_SESSION_KEY] = True

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
    Persiste l'état déplié/replié de la section « Patrimoine » en session.

    Le visuel (chevron + accordéon) est piloté en CSS pur côté template (checkbox +
    group-has-[:checked]) → ce POST est un simple fire-and-forget (hx-swap="none") qui
    ne renvoie rien à afficher. On lit l'état RÉEL de la checkbox (`open` présent =
    cochée) plutôt que d'inverser, pour rester synchrone avec le client sans risque de
    désync. Réponse 204 : aucun contenu à échanger.
    """
    request.session[SIDEBAR_SESSION_KEY] = "open" in request.POST
    return HttpResponse(status=204)

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
from django.http import Http404
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
    Bascule l'état déplié/replié de la section « Patrimoine » en session, puis re-rend
    le bloc nav (HTMX `outerHTML` swap de #patrimoine-nav).

    Le toggle ne change PAS la page courante : on préserve donc la surbrillance via les
    champs envoyés en hx-vals (active_slug du sous-item, on_overview du label). Sans ça,
    le re-render perdrait l'état actif (la requête de toggle n'a ni slug ni url 'overview').
    """
    request.session[SIDEBAR_SESSION_KEY] = not request.session.get(
        SIDEBAR_SESSION_KEY, False
    )
    # Override explicite des clés du context processor (la requête de toggle ne porte
    # pas l'URL de la page réelle) — le contexte de vue a priorité sur le processor.
    # On borne active_slug aux slugs connus : valeur réinjectée dans hx-vals du partial,
    # donc on ne lui fait pas confiance même si l'auto-escape Django neutralise l'injection.
    raw_slug = request.POST.get("active_slug")
    ctx = {
        "active_asset_class_slug": raw_slug
        if raw_slug and get_asset_class(raw_slug)
        else None,
        "patrimoine_on_overview": request.POST.get("on_overview") == "1",
    }
    return render(request, "components/layout/_patrimoine_nav.html", ctx)

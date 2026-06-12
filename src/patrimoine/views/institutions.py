"""
patrimoine/views/institutions.py — picker d'institutions (« Compléter mon patrimoine »).

Panneau droit qui liste le catalogue (logo + nom) avec recherche live HTMX.
Aperçu minimal du futur wizard de création de compte (#73) — ici lecture seule :
on ne fait que CHOISIR/voir une institution, la création vient ensuite.

Catalogue global (pas de scoping user : une Institution n'appartient à personne)
→ pas d'IDOR à ajouter ici, juste login_required.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Institution
from services import logos

logger = logging.getLogger(__name__)


def _row_context(institution: Institution) -> dict:
    """Contexte d'une ligne du picker : institution + URL logo résolue (ou "")."""
    icon_map = logos.get_institution_icon_map()
    return {
        "institution": institution,
        "icon_url": icon_map.get(institution.icon_slug or institution.slug, ""),
    }


@login_required
def institution_picker(request):
    """Liste les institutions actives (logo + nom), filtrée par ?q= (recherche live)."""
    # Endpoint HTMX (injecté dans #panel-content) : une navigation directe ne doit pas
    # renvoyer un partial nu sans <html>/<head>. Même garde que les autres vues
    # patrimoine (overview.py / asset_class.py) → on redirige vers le bilan.
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:overview")

    query = request.GET.get("q", "").strip()
    qs = Institution.objects.filter(is_active=True)
    if query:
        qs = qs.filter(name__icontains=query)

    # Logo résolu UNE fois (scan disque mis en cache) puis apparié à chaque institution :
    # la recherche live re-rend la liste à chaque frappe → pas d'appel de tag (disk I/O)
    # par ligne. Liste de paires plutôt qu'un attribut posé sur le modèle (mypy-safe).
    icon_map = logos.get_institution_icon_map()
    rows = [
        {"institution": inst, "icon_url": icon_map.get(inst.icon_slug or inst.slug, "")}
        for inst in qs.order_by("country", "name")
    ]

    return render(
        request,
        "patrimoine/partials/_institution_picker.html",
        {"rows": rows, "q": query},
    )


@login_required
def institution_logo_form(request, slug: str):
    """Ouvre le formulaire de réparation de logo (GET, HTMX) → remplace la ligne picker."""
    # Endpoint HTMX (partial nu) : navigation directe → redirige (cf. institution_picker).
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:overview")
    institution = get_object_or_404(
        Institution.objects.filter(is_active=True), slug=slug
    )
    return render(
        request,
        "patrimoine/partials/_logo_repair_form.html",
        {"institution": institution},
    )


@login_required
@require_POST
def institution_logo_repair(request, slug: str):
    """
    Installe un logo collé à la main (#128). Succès → re-rend la ligne (logo affiché) ;
    échec → re-rend le formulaire en 422 avec le message. Validation DANS la vue.
    """
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:overview")
    institution = get_object_or_404(
        Institution.objects.filter(is_active=True), slug=slug
    )
    url = request.POST.get("logo_url", "").strip()

    if not url.startswith("https://") or len(url) > 500:
        # Rejet d'une action utilisateur → WARNING (visible en prod, cohérent avec les
        # rejets logo_fetch du service ; DEBUG disparaîtrait sous LOG_LEVEL=WARNING).
        logger.warning(
            "logo_repair rejected institution=%s reason=bad_url user=%s",
            institution.slug,
            request.user.id,
        )
        return render(
            request,
            "patrimoine/partials/_logo_repair_form.html",
            {"institution": institution, "error": "URL https valide obligatoire."},
            status=422,
        )

    name = logos.fetch_from_url(url, institution.icon_slug or institution.slug)
    if name is None:
        # fetch_from_url a déjà loggé la cause précise (logo_fetch refused/failed).
        return render(
            request,
            "patrimoine/partials/_logo_repair_form.html",
            {
                "institution": institution,
                "error": "Image impossible à installer (format, taille ou URL invalide).",
            },
            status=422,
        )

    logger.info(
        "logo_repair ok institution=%s user=%s name=%s",
        institution.slug,
        request.user.id,
        name,
    )
    return render(
        request,
        "patrimoine/partials/_institution_picker_row.html",
        _row_context(institution),
    )

"""
patrimoine/views/institutions.py — picker d'institutions (« Compléter mon patrimoine »).

Panneau droit qui liste le catalogue (logo + nom) avec recherche live HTMX.
Aperçu minimal du futur wizard de création de compte (#73) — ici lecture seule :
on ne fait que CHOISIR/voir une institution, la création vient ensuite.

Catalogue global (pas de scoping user : une Institution n'appartient à personne)
→ pas d'IDOR à ajouter ici, juste login_required.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.models import Institution
from budget.utils import _resolve_bank_icon_map


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
    icon_map = _resolve_bank_icon_map()
    rows = [
        {"institution": inst, "icon_url": icon_map.get(inst.icon_slug or inst.slug, "")}
        for inst in qs.order_by("country", "name")
    ]

    return render(
        request,
        "patrimoine/partials/_institution_picker.html",
        {"rows": rows, "q": query},
    )

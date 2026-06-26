"""
budget/context_processors.py — Données globales injectées dans tous les templates.

Ajouté à TEMPLATES.OPTIONS.context_processors dans config/settings.py.
Évite à chaque vue de re-passer les mêmes constantes au template.
"""

import json
from datetime import date

from django.db.models import Sum
from django.db.models.functions import Coalesce

from budget.constants import CATEGORY_COLOR_PALETTE
from services.colors import palette_dict as derived_palette_dict

# Anneau du badge objectif quand l'objectif est DÉPASSÉ (> 100 %) : rouge.
# = valeur EXACTE du token Tailwind "expense" (tailwind.config.js) — à garder
# synchro avec lui si le token change (≠ GAUGE_COLOR_WARNING qui est l'orange #f97316).
OVERSPEND_RING_COLOR = "#e5494a"


def budget_objectives(request):
    """Objectifs budget de l'utilisateur → badges jauge dans la topbar (#24).

    Présent sur TOUTES les pages (topbar = base_app.html). Une entrée par
    BudgetTarget : on calcule le dépensé du MOIS COURANT sur la catégorie et le %
    consommé (même filtre que budget_index). Anonyme / aucun objectif → liste vide.

    Coût : 2 requêtes légères par requête authentifiée (objectifs + dépensé groupé).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"topbar_objectives": []}

    # Court-circuit : une requête HTMX rend un partial/fragment, JAMAIS la topbar
    # (qui vit dans base_app.html). On évite 2 requêtes DB inutiles par interaction
    # HTMX (filtres, toggles, pagination…). Header brut, cf. rules/htmx.md.
    if request.headers.get("HX-Request"):
        return {"topbar_objectives": []}

    # Imports locaux : éviter un import circulaire au chargement des settings
    # (ce module est importé tôt via TEMPLATES.context_processors).
    from transactions.models import BudgetTarget, Transaction

    targets = list(
        BudgetTarget.objects.for_user(user)
        .select_related("category")
        .order_by("category__order", "category__name")
    )
    if not targets:
        return {"topbar_objectives": []}

    today = date.today()
    month_start = today.replace(day=1)
    spent = {
        row["category_id"]: abs(float(row["total"] or 0))
        for row in Transaction.objects.for_user(user)
        .filter(
            date__gte=month_start,
            date__lte=today,
            amount__lt=0,
            is_ignored=False,
            is_internal_transfer=False,
            category__isnull=False,
        )
        .values("category_id")
        .annotate(total=Sum(Coalesce("amount_chf", "amount")))
    }

    objectives = []
    for target in targets:
        amount = float(target.amount)
        consumed = spent.get(target.category_id, 0.0)
        raw_pct = round(consumed / amount * 100) if amount > 0 else 0
        over = raw_pct > 100
        objectives.append(
            {
                "name": target.category.name,
                "slug": target.category.slug,
                "icon": target.category.icon,
                "colour_hex": target.category.colour_hex,
                # Anneau rouge si dépassement, sinon couleur de la catégorie.
                "ring_color": OVERSPEND_RING_COLOR
                if over
                else target.category.colour_hex,
                "spent": round(consumed),
                "target": round(amount),
                "raw_pct": raw_pct,  # non cappé (texte / couleur)
                "pct": min(raw_pct, 100),  # cappé pour l'arc SVG
                "overspend": round(consumed - amount) if over else None,
            }
        )
    return {"topbar_objectives": objectives}


def design_tokens(request):
    """
    Expose les couleurs Python dans `window.BRICBUDGET_TOKENS` (charts, picker).

    Pourquoi : les scripts JS utilisent les couleurs sans dupliquer les listes dans
    `static/js/`. Source de vérité unique en Python. Règle existante : zéro hex inline en JS.

    Deux clés injectées dans base.html :
      - `category_palette_json` → `.categories` : {"ocre": "#eed8b4", ...} (catégories budget) ;
      - `derived_palette_json`  → `.palette`    : {"primary": [...], "light": [...], "dark": [...]}
        (palette dérivée #134 — tiers d'allocation pour comptes / institutions / positions).
    """
    palette_dict = {c["name"].lower(): c["hex"] for c in CATEGORY_COLOR_PALETTE}
    return {
        "category_palette_json": json.dumps(palette_dict),
        "derived_palette_json": json.dumps(derived_palette_dict()),
    }

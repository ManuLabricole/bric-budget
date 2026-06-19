"""
budget/views_categories.py — Vues de détail et gestion des catégories.

Contient :
    - Page détail d'une catégorie (category_detail) + cashflow fragment
    - Panel de gestion CRUD catégories (category_manage, create, delete)
"""

import calendar
import logging
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Account
from budget.constants import (
    CATEGORY_COLOR_PALETTE,
    CURATED_ICONS,
    MOIS_FR,
    PERIOD_MODE_MONTHS,
)
from budget.utils import (
    _add_months,
    _cats_with_subcats,
    _generate_unique_slug,
    _period_from_session,
    _seg_factor,
    _vary_color,
)
from services.logos import get_institution_icon_map
from transactions.models import (
    BudgetTarget,
    CategorizationRule,
    Category,
    SubCategory,
    Transaction,
)

logger = logging.getLogger(__name__)

# =============================================================================
# _compute_category_cashflow_context — données communes Cashflow card + fragment
# =============================================================================


def _compute_category_cashflow_context(request, category):
    """
    Calcule le contexte de la carte Cashflow de category_detail.html.
    Partagé par budget_category_detail (page complète) et
    budget_category_cashflow_fragment (refresh HTMX partiel après toggle).
    """
    period_start, period_end = _period_from_session(request.session)
    period_mode = request.session.get("budget_period_mode", "1m")
    if period_mode == "1m":
        period_label = f"{MOIS_FR[period_start.month]} {period_start.year}"
    else:
        period_label = (
            f"{MOIS_FR[period_start.month]} — "
            f"{MOIS_FR[period_end.month]} {period_end.year}"
        )

    filter_account_ids = request.session.get("budget_filter_accounts_hidden", [])

    base_qs = Transaction.objects.for_user(request.user).filter(
        category=category,
        date__gte=period_start,
        date__lte=period_end,
    )
    if filter_account_ids:
        base_qs = base_qs.exclude(account_id__in=filter_account_ids)
    txs_active = base_qs.filter(is_ignored=False)

    total_amount = (
        txs_active.aggregate(total=Sum(Coalesce("amount_chf", "amount")))["total"] or 0
    )
    subcat_list = list(
        txs_active.filter(subcategory__isnull=False)
        .values(
            "subcategory__id",
            "subcategory__name",
            "subcategory__slug",
            "subcategory__icon",
            "subcategory__is_system",
        )
        .annotate(total=Sum(Coalesce("amount_chf", "amount")))
        .order_by("total")
    )

    cat_color = category.colour_hex or "#4ade80"
    source_name = category.name + "​"  # U+200B ZWSP — nœud source unique ECharts
    n_segs = len(subcat_list)
    subcat_colors = [
        _vary_color(cat_color, _seg_factor(i, n_segs)) for i in range(n_segs)
    ]

    sankey_nodes = [
        {"name": source_name, "slug": category.slug, "itemStyle": {"color": cat_color}}
    ]
    sankey_links = []
    for i, sub in enumerate(subcat_list):
        sankey_nodes.append(
            {
                "name": sub["subcategory__name"],
                "slug": sub["subcategory__slug"],
                "itemStyle": {"color": subcat_colors[i]},
            }
        )
        sankey_links.append(
            {
                "source": source_name,
                "target": sub["subcategory__name"],
                "value": round(float(abs(sub["total"])), 2),
            }
        )

    categorized_amount = sum(float(abs(sub["total"])) for sub in subcat_list)
    uncategorized_amount = abs(float(total_amount)) - categorized_amount
    uncat_color = _vary_color(cat_color, 0.20)
    if uncategorized_amount > 0.01:
        sankey_nodes.append(
            {
                "name": category.name,
                "slug": category.slug,
                "itemStyle": {"color": uncat_color},
            }
        )
        sankey_links.append(
            {
                "source": source_name,
                "target": category.name,
                "value": round(uncategorized_amount, 2),
            }
        )
    if not sankey_links and total_amount != 0:
        sankey_nodes.append(
            {
                "name": category.name,
                "slug": category.slug,
                "itemStyle": {"color": cat_color},
            }
        )
        sankey_links.append(
            {
                "source": source_name,
                "target": category.name,
                "value": round(float(abs(total_amount)), 2),
            }
        )

    sankey_data = {"nodes": sankey_nodes, "links": sankey_links}
    has_sankey = len(sankey_links) > 0

    tx_count = txs_active.count()
    cat_tab = request.session.get("budget_cat_tab", "transactions")
    subcat_count = (
        txs_active.filter(subcategory__isnull=False)
        .values("subcategory_id")
        .distinct()
        .count()
    )
    period_months = PERIOD_MODE_MONTHS.get(period_mode, 1)
    budget_target = BudgetTarget.objects.filter(category=category).first()

    target_amount = target_pct = on_track = arc_fill_px = None
    if budget_target:
        target_amount = budget_target.amount * Decimal(period_months)
        spent = abs(total_amount)
        target_pct = (
            round(float(spent / target_amount) * 100) if target_amount > 0 else 0
        )
        on_track = spent <= target_amount
        arc_fill_px = round(min(target_pct, 100) / 100 * 125.66, 1)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "period_mode": period_mode,
        "period_label": period_label,
        "period_months": period_months,
        "filter_account_ids": filter_account_ids,
        "base_qs": base_qs,
        "txs_active": txs_active,
        "total_amount": total_amount,
        "subcat_list": subcat_list,
        "subcat_colors": subcat_colors,
        "cat_color": cat_color,
        "uncategorized_amount": uncategorized_amount,
        "uncat_color": uncat_color,
        "sankey_data": sankey_data,
        "has_sankey": has_sankey,
        "tx_count": tx_count,
        "cat_tab": cat_tab,
        "subcat_count": subcat_count,
        "budget_target": budget_target,
        "target_amount": target_amount,
        "target_pct": target_pct,
        "on_track": on_track,
        "arc_fill_px": arc_fill_px,
    }


# =============================================================================
# budget_category_cashflow_fragment — Partial HTMX : carte Cashflow seule (GET)
# =============================================================================


@login_required
def budget_category_cashflow_fragment(request, slug):
    """
    Partial HTMX — recalcule et retourne l'inner HTML de #cashflow-card.

    URL    : GET /budget/categorie/<slug>/cashflow/
    Target : #cashflow-card   swap="innerHTML"
    Template : budget/_category_cashflow_card_inner.html

    Appelé automatiquement depuis category_detail.html (JS htmx:afterSwap)
    après un toggle is_ignored depuis le panneau détail, pour mettre à jour
    le Sankey et les KPIs sans recharger toute la page.
    """
    # for_user : slug non unique global (#137) → système OU à moi.
    category = get_object_or_404(Category.objects.for_user(request.user), slug=slug)
    cc = _compute_category_cashflow_context(request, category)
    return render(
        request,
        "budget/_category_cashflow_card_inner.html",
        {
            "category": category,
            "period_label": cc["period_label"],
            "has_sankey": cc["has_sankey"],
            "sankey_data": cc["sankey_data"],
            "cat_tab": cc["cat_tab"],
            "total_amount": cc["total_amount"],
            "subcat_count": cc["subcat_count"],
            "budget_target": cc["budget_target"],
            "target_amount": cc["target_amount"],
            "arc_fill_px": cc["arc_fill_px"],
        },
    )


# =============================================================================
# budget_category_tx_fragment — Fragment liste transactions (search HTMX)
# =============================================================================


@login_required
def budget_category_tx_fragment(request, slug):
    """
    Partial HTMX — liste de transactions filtrées par catégorie + recherche.

    URL      : GET /budget/categorie/<slug>/transactions/?q=<search>
    Target   : #cat-tx-results  swap="outerHTML"
    Template : budget/partials/_category_tx_fragment.html
    """
    # for_user : slug non unique global (#137) → système OU à moi.
    category = get_object_or_404(Category.objects.for_user(request.user), slug=slug)
    q = request.GET.get("q", "").strip()
    # Respecter la période active en session — même clé que budget_index
    period_start, period_end = _period_from_session(request.session)
    qs = Transaction.objects.for_user(request.user).filter(
        category=category,
        is_ignored=False,
        date__gte=period_start,
        date__lte=period_end,
    )
    if q:
        qs = qs.filter(display_name__icontains=q)
    qs = qs.select_related("account", "account__institution", "subcategory").order_by(
        "-date"
    )[:50]
    return render(
        request,
        "budget/partials/_category_tx_fragment.html",
        {"transactions": qs, "q": q, "category": category},
    )


# =============================================================================
# budget_category_detail — Page détail d'une catégorie
# =============================================================================


@login_required
def budget_category_detail(request, slug):
    """
    Page détail d'une catégorie : Sankey sous-catégories + liste de transactions.

    URL : /budget/categorie/<slug>/
    Template : budget/category_detail.html

    Ce que cette vue calcule :
        - La catégorie par slug (404 si inconnue)
        - La période active (lue depuis la session — même clé que budget_index)
        - Les transactions de cette catégorie sur la période
        - Le total et le nombre de transactions (KPIs)
        - Les sous-totaux par sous-catégorie (pour le Sankey)

    Le Sankey ici est "direct" (sans nœud pool) :
        Category → SubCategory1, Category → SubCategory2, ...
    La même fonction BricCharts.initSankey() gère ce cas via la détection
    automatique de l'absence de "__pool__" dans les nœuds.
    """

    # for_user : slug non unique global (#137) → système OU à moi.
    category = get_object_or_404(Category.objects.for_user(request.user), slug=slug)

    cc = _compute_category_cashflow_context(request, category)
    period_start = cc["period_start"]
    period_end = cc["period_end"]
    period_mode = cc["period_mode"]

    today = date.today()
    current_month_end = today.replace(
        day=calendar.monthrange(today.year, today.month)[1]
    )
    can_go_next = period_end < current_month_end

    accounts = (
        Account.objects.for_user(request.user)
        .filter(is_active=True)
        .select_related("institution")
        .order_by("institution__name", "name")
    )

    txs = (
        cc["base_qs"]
        .select_related("subcategory", "account", "account__institution")
        .order_by("-date", "-id")
    )
    institution_icon_map = get_institution_icon_map()
    for tx in txs:
        icon_slug = (
            tx.account.institution.icon_slug
            if tx.account and tx.account.institution
            else ""
        )
        tx.institution_icon_url = institution_icon_map.get(icon_slug, "")

    avg_amount = (cc["total_amount"] / cc["tx_count"]) if cc["tx_count"] > 0 else None

    # ── Distribution donut (panel droit) — même palette de couleurs que le Sankey ──
    donut_segments = [
        {
            "name": sub["subcategory__name"],
            "value": round(float(abs(sub["total"])), 2),
            "itemStyle": {"color": cc["subcat_colors"][i]},
        }
        for i, sub in enumerate(cc["subcat_list"])
    ]
    if cc["uncategorized_amount"] > 0.01:
        donut_segments.append(
            {
                "name": category.name,
                "value": round(cc["uncategorized_amount"], 2),
                "itemStyle": {"color": cc["uncat_color"]},
            }
        )
    if not donut_segments and cc["total_amount"] != 0:
        donut_segments = [
            {
                "name": category.name,
                "value": round(float(abs(cc["total_amount"])), 2),
                "itemStyle": {"color": cc["cat_color"]},
            }
        ]
    donut_data = {
        "segments": donut_segments,
        "label": "Distribution",
        "sign": "−" if cc["total_amount"] < 0 else "+",
        "total": round(float(abs(cc["total_amount"])), 2),
    }
    has_donut = len(donut_segments) > 0

    # remaining_abs_chf : marge / dépassement objectif (affichage panel droit)
    remaining_chf = None
    remaining_abs_chf = None
    if cc["budget_target"] and cc["target_amount"]:
        remaining_chf = round(
            float(cc["target_amount"]) - float(abs(cc["total_amount"])), 2
        )
        remaining_abs_chf = abs(remaining_chf)

    # ── Historique mensuel — 12 mois glissants pour le bar chart ─────────────
    # Indépendant de la période active en session : toujours les 12 derniers mois.
    # Utilisé uniquement dans le tab "objectif" pour visualiser la tendance.
    twelve_months_ago = _add_months(today.replace(day=1), -11)
    monthly_qs = (
        Transaction.objects.for_user(request.user)
        .filter(
            category=category,
            date__gte=twelve_months_ago,
            date__lte=today,
            is_ignored=False,
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum(Coalesce("amount_chf", "amount")))
        .order_by("month")
    )

    history_months = []
    history_values = []
    history_urls = []
    for row in monthly_qs:
        m = row["month"]
        history_months.append(MOIS_FR[m.month][:3])
        # Valeur absolue — le bar chart affiche toujours positif
        history_values.append(round(float(abs(row["total"])), 2))
        history_urls.append(reverse("budget:set_period_month", args=[m.year, m.month]))

    history_chart_data = {
        "months": history_months,
        "values": history_values,
        "urls": history_urls,
        # Ligne de référence — montant mensuel brut (pas multiplié par period_months)
        "target": round(float(cc["budget_target"].amount), 2)
        if cc["budget_target"]
        else None,
        # current_month permet à bar.js de colorer la barre active avec la couleur catégorie
        "current_month": period_start.strftime("%Y-%m"),
        # Couleur catégorie — barres actives et ligne objectif
        "cat_color": cc["cat_color"],
    }
    has_history = len(history_months) > 0

    # ── KPI stats sous le bar chart ───────────────────────────────────────────
    # Calculés uniquement si budget_target existe (sinon affichage vide + CTA).
    # Sont des faits fixes sur 12 mois glissants — indépendants de la période.
    bar_kpis = None
    if cc["budget_target"] and has_history:
        D = Decimal
        target_monthly = float(cc["budget_target"].amount)

        # Dépenses moyennes sur les 12 mois de l'historique
        avg_monthly = sum(history_values) / len(history_values)

        # Meilleure série : nb de mois consécutifs sous objectif (max streak)
        best_streak = current_streak = 0
        for v in history_values:
            if v <= target_monthly:
                current_streak += 1
                best_streak = max(best_streak, current_streak)
            else:
                current_streak = 0

        # % Dépenses année en cours : total jan→aujourd'hui / (target × mois écoulés)
        year_start = today.replace(month=1, day=1)
        year_spent_agg = Transaction.objects.for_user(request.user).filter(
            category=category,
            date__gte=year_start,
            date__lte=today,
            is_ignored=False,
        ).aggregate(total=Sum(Coalesce("amount_chf", "amount")))["total"] or D(0)
        year_months_elapsed = today.month  # nb de mois depuis janvier (inclusif)
        year_target = target_monthly * year_months_elapsed
        year_pct = (
            round(float(abs(year_spent_agg)) / year_target * 100)
            if year_target > 0
            else 0
        )

        # Dépassement d'objectif : % de mois (sur 12) où le budget a été dépassé
        months_over = sum(1 for v in history_values if v > target_monthly)
        over_pct = round(months_over / len(history_values) * 100)

        bar_kpis = {
            "avg_monthly": round(avg_monthly, 0),
            "best_streak": best_streak,
            "year_pct": year_pct,
            "over_pct": over_pct,
            "year_months_elapsed": year_months_elapsed,
        }

    return render(
        request,
        "budget/category_detail.html",
        {
            "category": category,
            "period_start": period_start,
            "period_end": period_end,
            "period_label": cc["period_label"],
            "total_amount": cc["total_amount"],
            "tx_count": cc["tx_count"],
            "avg_amount": avg_amount,
            "txs": txs,
            "subcat_list": cc["subcat_list"],
            "sankey_data": cc["sankey_data"],
            "has_sankey": cc["has_sankey"],
            "donut_data": donut_data,
            "has_donut": has_donut,
            "cat_tab": cc["cat_tab"],
            "subcat_count": cc["subcat_count"],
            "budget_target": cc["budget_target"],
            "target_amount": cc["target_amount"],
            "target_pct": cc["target_pct"],
            "on_track": cc["on_track"],
            "arc_fill_px": cc["arc_fill_px"],
            "remaining_chf": remaining_chf,
            "remaining_abs_chf": remaining_abs_chf,
            "period_months": cc["period_months"],
            "period_mode": period_mode,
            "period_display": cc["period_label"],
            "can_go_next": can_go_next,
            "history_chart_data": history_chart_data,
            "has_history": has_history,
            "bar_kpis": bar_kpis,
            # Filtres compte — partagés avec budget_index via la session
            "accounts": accounts,
            "filter_account_ids": cc["filter_account_ids"],
        },
    )


# =============================================================================
# Catégories — Gestion (panel liste + détail) — Phase 2G T3
# =============================================================================


@login_required
def budget_panel_category_manage(request):
    """
    Panel de gestion des catégories : liste toutes les catégories avec leurs stats.

    URL  : GET /budget/panel/category-manage/
    HTMX : hx-target="#modal-content" hx-swap="innerHTML"

    Chaque catégorie est annotée avec :
    - subcat_count : nombre de sous-catégories
    - tx_count     : nombre de transactions directement liées
    - rules_count  : nombre de règles liées
    """
    # tx_count scopé à l'user connecté : Count("transactions") sans filtre compterait
    # les transactions de tous les users → fuite de données en contexte multi-user.
    # Django supporte Count(filter=Q(...)) depuis 2.0 — agrégat conditionnel SQL FILTER.
    cats = (
        Category.objects.for_user(request.user)
        .filter(is_active=True)
        .annotate(
            # subcat_count scopé : une sous-cat perso d'un AUTRE user rattachée à
            # une catégorie système ne doit pas gonfler le compteur de cet user (#137).
            subcat_count=Count(
                "subcategories",
                filter=Q(subcategories__owner__isnull=True)
                | Q(subcategories__owner=request.user),
                distinct=True,
            ),
            tx_count=Count(
                "transactions",
                filter=Q(transactions__account__members=request.user),
                distinct=True,
            ),
            rules_count=Count("rules", distinct=True),
        )
        .order_by("order", "name")
    )
    return render(request, "budget/_panel_category_manage.html", {"cats": cats})


@login_required
def budget_panel_category_manage_detail(request, slug):
    """
    Panel de détail d'une catégorie : sous-catégories + règles liées.

    URL  : GET /budget/panel/category-manage/<slug>/
    HTMX : hx-target="#modal-content" hx-swap="innerHTML"
    Bouton ← : hx-get vers budget_panel_category_manage (retour à la liste).
    """
    # for_user : une catégorie perso d'un autre user → 404 (pas de fuite de son détail).
    cat = get_object_or_404(
        Category.objects.for_user(request.user), slug=slug, is_active=True
    )

    # tx_count scopé : même logique que budget_panel_category_manage.
    # Les sous-cats listées sont elles aussi scopées (système OU à moi) pour ne pas
    # exposer une sous-cat perso d'un autre user rattachée à une catégorie système.
    subcats = (
        cat.subcategories.filter(Q(owner__isnull=True) | Q(owner=request.user))
        .annotate(
            tx_count=Count(
                "transactions",
                filter=Q(transactions__account__members=request.user),
                distinct=True,
            ),
            rules_count=Count("rules", distinct=True),
        )
        .order_by("name")
    )

    # Règles directement liées à cette catégorie principale
    rules = (
        CategorizationRule.objects.filter(category=cat)
        .select_related("subcategory")
        .order_by("-priority", "keyword")
    )

    # Comptage global transactions (directes + via sous-catégories) — filtré par user
    tx_direct = Transaction.objects.for_user(request.user).filter(category=cat).count()
    tx_via_subcats = (
        Transaction.objects.for_user(request.user)
        .filter(subcategory__category=cat)
        .count()
    )

    return render(
        request,
        "budget/_panel_category_manage_detail.html",
        {
            "cat": cat,
            "subcats": subcats,
            "rules": rules,
            "tx_direct": tx_direct,
            "tx_via_subcats": tx_via_subcats,
        },
    )


# =============================================================================
# Catégories — Création (Phase 2G T3)
# =============================================================================


@login_required
def budget_panel_category_create(request):
    """
    Charge le panel de création de catégorie ou sous-catégorie dans #modal-content.

    URL  : GET /budget/panel/category-create/
    HTMX : hx-target="#modal-content" hx-swap="innerHTML"

    Passe au template :
    - icon_names    : liste triée des noms de fichiers SVG disponibles (sans extension)
    - cats_with_subcats : pour le picker de catégorie parente (sous-cat uniquement)
    - color_palette : CATEGORY_COLOR_PALETTE — 16 couleurs pastels
    """
    _, cats_with_subcats = _cats_with_subcats(request.user)

    return render(
        request,
        "budget/_panel_category_create.html",
        {
            "available_icons": CURATED_ICONS,
            "cats_with_subcats": cats_with_subcats,
            "color_palette": CATEGORY_COLOR_PALETTE,
        },
    )


@login_required
@require_POST
def budget_category_create_submit(request):
    """
    Crée une Category ou SubCategory depuis le formulaire du panel.

    URL  : POST /budget/category/create/submit/
    HTMX : hx-target="#modal-content" hx-swap="innerHTML"

    Champs POST :
        cat_type    : "main" (Category) | "sub" (SubCategory)
        name        : nom affiché (ex : "Médecine douce")
        icon        : nom fichier SVG sans extension (ex : "heartbeat")
        colour_hex  : ex "#e77f79" — obligatoire si cat_type="main"
        parent_id   : id Category parente — obligatoire si cat_type="sub"

    En cas d'erreur : re-render le panel avec les erreurs et valeurs pré-remplies.
    En cas de succès : render le même template en mode "success" (écran de confirmation).
    """
    cat_type = request.POST.get("cat_type", "main")
    name = request.POST.get("name", "").strip()
    icon = request.POST.get("icon", "")
    errors = []

    if not name:
        errors.append("Le nom est obligatoire.")
    if not icon:
        errors.append("Choisissez une icône.")

    obj_label = ""
    obj_type_label = ""

    if not errors:
        if cat_type == "main":
            colour_hex = request.POST.get("colour_hex", "")
            if not colour_hex:
                errors.append("Choisissez une couleur.")
            else:
                # Unicité scopée par owner (#137) : on bloque seulement si une
                # catégorie VISIBLE par ce user (système ou sa perso) porte déjà ce
                # nom. La perso d'un AUTRE user portant le même nom est autorisée.
                if (
                    Category.objects.for_user(request.user)
                    .filter(name__iexact=name)
                    .exists()
                ):
                    errors.append(f"Une catégorie « {name} » existe déjà.")
                else:
                    slug = _generate_unique_slug(name, Category, owner=request.user)
                    cat = Category.objects.create(
                        name=name,
                        slug=slug,
                        icon=icon,
                        colour_hex=colour_hex,
                        order=100,  # placée en fin de liste par défaut
                        is_system=False,
                        # owner = créateur → catégorie perso, jamais visible par
                        # un autre user (issue #137). is_system=False ⇒ owner non NULL.
                        owner=request.user,
                    )
                    logger.info(
                        "Category created: id=%s slug=%s by user=%s",
                        cat.id,
                        cat.slug,
                        request.user.id,
                    )
                    obj_label = name
                    obj_type_label = "catégorie principale"

        elif cat_type == "sub":
            parent_id = request.POST.get("parent_id", "").strip()
            if not parent_id:
                errors.append("Choisissez une catégorie parente.")
            else:
                # Scope for_user : on ne peut rattacher une sous-cat qu'à une
                # catégorie système ou à SA propre catégorie perso (#137 — sinon
                # IDOR en écriture sur la perso d'un autre user).
                parent = get_object_or_404(
                    Category.objects.for_user(request.user), id=parent_id
                )
                if SubCategory.objects.filter(
                    category=parent, name__iexact=name
                ).exists():
                    errors.append(
                        f"Une sous-catégorie « {name} » existe déjà dans {parent.name}."
                    )
                else:
                    slug = _generate_unique_slug(name, SubCategory, owner=request.user)
                    sub = SubCategory.objects.create(
                        category=parent,
                        name=name,
                        slug=slug,
                        icon=icon,
                        is_system=False,
                        # owner = créateur → sous-catégorie perso (issue #137).
                        owner=request.user,
                    )
                    logger.info(
                        "SubCategory created: id=%s slug=%s parent=%s by user=%s",
                        sub.id,
                        sub.slug,
                        parent.slug,
                        request.user.id,
                    )
                    obj_label = f"{name} (sous {parent.name})"
                    obj_type_label = "sous-catégorie"

    if errors:
        # Re-render avec erreurs + pré-remplissage (posted = dict des valeurs soumises)
        _, cats_with_subcats = _cats_with_subcats(request.user)
        return render(
            request,
            "budget/_panel_category_create.html",
            {
                "available_icons": CURATED_ICONS,
                "cats_with_subcats": cats_with_subcats,
                "color_palette": CATEGORY_COLOR_PALETTE,
                "errors": errors,
                "posted": request.POST,
            },
        )

    # Succès — même template, branche {% if success %} activée côté HTML
    return render(
        request,
        "budget/_panel_category_create.html",
        {
            "success": True,
            "obj_label": obj_label,
            "obj_type_label": obj_type_label,
        },
    )


# =============================================================================
# Catégories — Suppression (Phase 2G T3)
# =============================================================================


@login_required
def budget_panel_category_delete_confirm(request, obj_type, slug):
    """
    Affiche le panel de confirmation de suppression avec les counts d'impact.

    URL  : GET /budget/category/<obj_type>/<slug>/delete-confirm/
    HTMX : hx-target="#modal-content" hx-swap="innerHTML"

    obj_type : "category"    → supprime une Category (+ sous-cats CASCADE)
               "subcategory" → supprime une SubCategory (transactions → SET_NULL)

    Les catégories/sous-catégories système (is_system=True) retournent 403.
    """
    obj: Category | SubCategory
    if obj_type == "category":
        # for_user : le slug n'est plus unique globalement (#137) → scoper sur
        # système OU à moi, sinon MultipleObjectsReturned + IDOR sur la perso d'un autre.
        obj = get_object_or_404(Category.objects.for_user(request.user), slug=slug)
        assert isinstance(
            obj, Category
        )  # narrow mypy : for_user partagé Category/SubCategory
        if obj.is_system:
            return HttpResponse(
                "Catégorie système — suppression interdite.", status=403
            )
        tx_count = (
            Transaction.objects.for_user(request.user).filter(category=obj).count()
        )
        subcat_count = obj.subcategories.count()
        rules_count = CategorizationRule.objects.filter(category=obj).count()

    elif obj_type == "subcategory":
        obj = get_object_or_404(SubCategory.objects.for_user(request.user), slug=slug)
        assert isinstance(
            obj, SubCategory
        )  # narrow mypy : for_user partagé Category/SubCategory
        if obj.is_system:
            return HttpResponse(
                "Sous-catégorie système — suppression interdite.", status=403
            )
        tx_count = (
            Transaction.objects.for_user(request.user).filter(subcategory=obj).count()
        )
        subcat_count = 0
        rules_count = CategorizationRule.objects.filter(subcategory=obj).count()

    else:
        return HttpResponse("Type invalide.", status=400)

    delete_url = reverse("budget:category_delete", args=[obj_type, slug])

    return render(
        request,
        "budget/_panel_category_delete_confirm.html",
        {
            "obj": obj,
            "obj_type": obj_type,
            "tx_count": tx_count,
            "subcat_count": subcat_count,
            "rules_count": rules_count,
            "delete_url": delete_url,
        },
    )


@login_required
@require_POST
def budget_category_delete(request, obj_type, slug):
    """
    Supprime une Category ou SubCategory non-système.

    URL  : POST /budget/category/<obj_type>/<slug>/delete/
    HTMX : hx-target="#modal-content" hx-swap="innerHTML"

    Django exécute automatiquement toutes les cascades définies sur les ForeignKey :
    - Category supprimée → SubCategories CASCADE, BudgetTarget CASCADE,
      CategorizationRules CASCADE, Transaction.category SET_NULL
    - SubCategory supprimée → Transaction.subcategory SET_NULL,
      CategorizationRule.subcategory SET_NULL

    Après suppression, HTMX recharge /budget/ via l'en-tête HX-Redirect.
    """
    obj: Category | SubCategory
    if obj_type == "category":
        # for_user + is_system=False : on ne supprime que SA propre perso (#137).
        obj = get_object_or_404(
            Category.objects.for_user(request.user), slug=slug, is_system=False
        )
    elif obj_type == "subcategory":
        obj = get_object_or_404(
            SubCategory.objects.for_user(request.user), slug=slug, is_system=False
        )
    else:
        return HttpResponse("Type invalide.", status=400)

    logger.info(
        "Category/SubCategory deleted: type=%s slug=%s id=%s by user=%s",
        obj_type,
        obj.slug,
        obj.id,
        request.user.id,
    )
    obj.delete()

    # HX-Redirect demande à HTMX de naviguer vers /budget/ après la suppression.
    # Le modal se fermera automatiquement car la page se recharge entièrement.
    response = HttpResponse("")
    response["HX-Redirect"] = reverse("budget:index")
    return response

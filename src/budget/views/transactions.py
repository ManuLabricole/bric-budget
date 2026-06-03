"""
budget/views_transactions.py — Vues du panneau transactions (right panel).

Contient les vues HTMX du right panel :
    - Liste des transactions (panel_transactions, panel_navigate)
    - Détail d'une transaction (panel_tx_detail)
    - Toggle is_ignored / is_reconciled
    - Picker de catégorie (panel_category_picker, categorize_transaction)
    - Objectif mensuel (modal_target_create)
"""

import calendar
import json
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, InvalidPage, Paginator
from django.db.models.functions import Abs
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Account
from budget.constants import MOIS_FR, PERIOD_MODE_MONTHS, RULE_NOISE_TOKENS
from budget.utils import (
    _add_months,
    _period_end_from_start,
    _period_from_session,
    _resolve_bank_icon_map,
    safe_referer,
)
from transactions.models import BudgetTarget, Category, SubCategory, Transaction
from transactions.services import sync_internal_transfer

logger = logging.getLogger(__name__)


@login_required
def budget_modal_target_create(request):
    """
    GET  → retourne le formulaire de création d'objectif dans la modal centrale.
    POST → crée ou met à jour le BudgetTarget, puis redirige via HX-Redirect.

    Deux modes :
      - Avec category_id (depuis category_detail) : formulaire pré-rempli catégorie
      - Sans category_id (depuis index) : formulaire avec sélecteur de catégorie

    L'objectif est général (une seule valeur par catégorie, sans notion de mois).
    La vue category_detail multiplie ce montant selon le mode de période (1m/3m/1y).
    """
    category_id = request.POST.get("category_id") or request.GET.get("category_id")

    if request.method == "POST":
        category = get_object_or_404(Category, id=category_id)
        amount_str = request.POST.get("amount", "").replace(",", ".")
        try:
            amount = Decimal(str(amount_str))
        except (InvalidOperation, ValueError):
            return HttpResponse("Montant invalide", status=400)
        _, created = BudgetTarget.objects.update_or_create(
            category=category,
            defaults={"amount": amount},
        )
        log = logger.info if created else logger.debug
        log(
            "BudgetTarget %s: category=%s amount=%s by user=%s",
            "created" if created else "updated",
            category.slug,
            amount,
            request.user.id,
        )
        response = HttpResponse()
        response["HX-Redirect"] = safe_referer(request, "/budget/")
        return response

    # GET sans category_id → liste de toutes les catégories avec leur objectif actuel
    if not category_id:
        cats = Category.objects.filter(is_active=True).order_by("name")
        targets_by_cat = {t.category_id: t for t in BudgetTarget.objects.all()}
        categories_with_targets = [
            {"category": cat, "target": targets_by_cat.get(cat.id)} for cat in cats
        ]
        return render(
            request,
            "budget/_modal_target_list.html",
            {"categories_with_targets": categories_with_targets},
        )

    # GET avec category_id → formulaire pour cette catégorie (création ou modification)
    category = get_object_or_404(Category, id=category_id)
    existing_amount = None
    target = BudgetTarget.objects.filter(category=category).first()
    if target:
        existing_amount = target.amount

    return render(
        request,
        "budget/_modal_target_create.html",
        {
            "category": category,
            "existing_amount": existing_amount,
        },
    )


# =============================================================================
# budget_panel_transactions — Partial HTMX : liste transactions (right panel)
# =============================================================================


@login_required
def budget_panel_transactions(request):
    """
    Partial HTMX — chargé dans #panel-content quand on clique "Tout voir".

    URL : /budget/panel/transactions/
    Template : budget/_panel_tx_list.html  (fragment, pas une page complète)

    Principe :
        Cette vue ne retourne PAS une page HTML complète avec <html>/<head>/<body>.
        Elle retourne uniquement le fragment HTML qui sera injecté dans #panel-content
        par HTMX (hx-swap="innerHTML").

    Pourquoi lire la période depuis la session plutôt que la recalculer ?
        - La session contient déjà la période choisie par l'utilisateur.
        - Recalculer ici risquerait de désynchroniser (ex: si l'user a navigué en 3M).
        - Même source de vérité que budget_index().

    Limite à 200 transactions :
        - Au-delà, le right panel devient inutilisable (scroll infini).
        - La pagination sera ajoutée Phase 2A si besoin.
    """
    period_start, period_end = _period_from_session(request.session)
    today = date.today()

    # ── Icônes banque ─────────────────────────────────────────────────────────
    # Délégué au helper privé _resolve_bank_icon_map() — voir définition plus haut.
    bank_icon_map = _resolve_bank_icon_map()

    # ── Recherche texte libre (filtre live) ──────────────────────────────────
    #
    # "q" est envoyé par le composant search_bar.html via hx-get avec name="q".
    # On cherche dans display_name — le champ nettoyé canonical (Phase 2G).
    # icontains = insensible à la casse.
    q = request.GET.get("q", "").strip()

    # ── Filtre montant min/max (valeur absolue en CHF) ────────────────────────
    #
    # Le montant est filtré sur la valeur absolue du champ `amount`.
    # Limitation connue : pour les comptes non-CHF (EUR), `amount` est en devise
    # native. On filtre donc en EUR pour ces comptes. Acceptable pour l'usage actuel
    # (majorité des comptes sont CHF).
    def _parse_amount_filter(raw):
        """Retourne un entier positif ou None si invalide/vide."""
        try:
            v = int(float(raw)) if raw and raw.strip() else None
            return v if v and v > 0 else None
        except (ValueError, TypeError):
            return None

    amount_min = _parse_amount_filter(request.GET.get("amount_min", ""))
    amount_max = _parse_amount_filter(request.GET.get("amount_max", ""))

    # ── Filtres actifs — partagés avec budget_index via session ─────────────
    filter_account_ids = request.session.get("budget_filter_accounts_hidden", [])
    hidden_cat_slugs = request.session.get("budget_filter_categories_hidden", [])
    accounts = (
        Account.objects.for_user(request.user)
        .filter(is_active=True)
        .select_related("institution")
        .order_by("institution__name", "name")
    )
    all_categories = Category.objects.filter(is_active=True).order_by("order", "name")

    # ── Queryset transactions ─────────────────────────────────────────────────
    #
    # list() force l'évaluation du queryset pour pouvoir annoter les objets.
    # select_related → 1 JOIN au lieu de N+1 requêtes en template.
    # order_by("-date", "-id") → plus récentes en premier, "-id" = tie-breaker.
    #
    # Pas de filtre is_ignored=False ici — contrairement à budget_index()
    # qui exclut les ignorées des KPIs budget, le panel les affiche en grisé.
    # L'utilisateur doit voir ce qu'il a ignoré pour pouvoir le réactiver.
    qs = (
        Transaction.objects.for_user(request.user)
        .filter(
            date__gte=period_start,
            date__lte=period_end,
            is_internal_transfer=False,
        )
        .select_related("category", "subcategory", "account", "account__institution")
        .order_by("-date", "-id")
    )
    if filter_account_ids:
        qs = qs.exclude(account_id__in=filter_account_ids)
    if hidden_cat_slugs:
        qs = qs.exclude(category__slug__in=hidden_cat_slugs)
    if q:
        qs = qs.filter(display_name__icontains=q)
    if amount_min is not None or amount_max is not None:
        # Abs() annote chaque ligne avec la valeur absolue du montant.
        # On filtre ensuite dessus — les dépenses (négatives) et entrées (positives)
        # sont traitées de la même façon.
        qs = qs.annotate(abs_amount=Abs("amount"))
        if amount_min is not None:
            qs = qs.filter(abs_amount__gte=amount_min)
        if amount_max is not None:
            qs = qs.filter(abs_amount__lte=amount_max)

    # Pagination 50 tx/page — scroll infini côté client (HTMX "revealed").
    # ?page= est injecté par le sentinel HTMX en bas du scroll.
    # Page invalide ou hors-borne → retomber sur la première page.
    paginator = Paginator(qs, 50)
    try:
        page_number = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page_number = 1
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, InvalidPage):
        page_obj = paginator.page(1)
        page_number = 1

    tx_list = list(page_obj.object_list)

    # Annoter chaque transaction avec l'URL résolue de l'icône banque.
    # tx.bank_icon_url est ensuite accessible directement dans le template.
    for tx in tx_list:
        slug = (
            tx.account.institution.icon_slug
            if tx.account and tx.account.institution
            else ""
        )
        tx.bank_icon_url = bank_icon_map.get(slug, "")

    # ── Page > 1 = réponse "append-only" pour le scroll infini ─────────────────
    # Le sentinel HTMX en bas de liste fait un GET ?page=N.
    # On retourne uniquement les nouvelles lignes + un nouveau sentinel si besoin.
    # Pas de shell panel : HTMX remplace le sentinel par les nouvelles lignes.
    if page_number > 1:
        return render(
            request,
            "budget/_panel_tx_rows_append.html",
            {
                "transactions": tx_list,
                "page_obj": page_obj,
                "bank_icon_map": bank_icon_map,
                "q": q,
                "amount_min": amount_min,
                "amount_max": amount_max,
            },
        )

    period_mode = request.session.get("budget_period_mode", "1m")

    # ── Label période (format Finary : "1er mai. 2025 — 30 avr. 2026") ─────────
    day_start = "1er" if period_start.day == 1 else str(period_start.day)
    day_end = "1er" if period_end.day == 1 else str(period_end.day)
    period_label = (
        f"{day_start} {MOIS_FR[period_start.month][:3].lower()}. {period_start.year}"
        f" — "
        f"{day_end} {MOIS_FR[period_end.month][:3].lower()}. {period_end.year}"
    )

    # ── Bouton "suivant" masqué si on est déjà au mois courant ──────────────────
    current_month_end = today.replace(
        day=calendar.monthrange(today.year, today.month)[1]
    )
    can_go_next = period_end < current_month_end

    return render(
        request,
        "budget/_panel_tx_list.html",
        {
            "transactions": tx_list,
            "period_start": period_start,
            "period_end": period_end,
            "period_mode": period_mode,
            "period_label": period_label,
            "can_go_next": can_go_next,
            # Filtres — partagés via la session
            "accounts": accounts,
            "filter_account_ids": filter_account_ids,
            "acc_filter_open": getattr(request, "_panel_acc_filter_open", False),
            "all_categories": all_categories,
            "hidden_cat_slugs": hidden_cat_slugs,
            "page_obj": page_obj,
            # q + montant transmis au template pour l'URL du sentinel scroll infini
            "q": q,
            "amount_min": amount_min,
            "amount_max": amount_max,
        },
    )


# =============================================================================
# budget_panel_navigate — Met à jour la période puis retourne le fragment panel
# =============================================================================


@login_required
def budget_panel_navigate(request, action):
    """
    Partial HTMX — met à jour la période en session puis retourne le fragment
    liste transactions (même résultat que budget_panel_transactions, mais après
    avoir modifié la période).

    URL : /budget/panel/transactions/<action>/
    action : "prev" | "next" | "1m" | "3m" | "1y"

    Pourquoi ne pas réutiliser budget_set_period ?
        budget_set_period fait un redirect (pattern PRG pour éviter F5 double).
        Ici on est en HTMX : on veut retourner un fragment, pas une redirection.
        On duplique la logique de session update, puis on appelle
        budget_panel_transactions() directement pour le rendu.
    """
    today = date.today()
    current_mode = request.session.get("budget_period_mode", "1m")
    start_str = request.session.get("budget_period_start")
    current_start = date.fromisoformat(start_str) if start_str else today.replace(day=1)

    if action in PERIOD_MODE_MONTHS:
        # Changement de mode : on tente de garder le même mois de départ
        new_mode = action
        new_start = current_start
        new_end = _period_end_from_start(new_start, new_mode)
        current_month_end = today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        )
        if new_end > current_month_end:
            n = PERIOD_MODE_MONTHS[new_mode]
            new_start = _add_months(today.replace(day=1), -(n - 1))
            new_end = _period_end_from_start(new_start, new_mode)

    elif action == "prev":
        new_mode = current_mode
        new_start = _add_months(current_start, -1)
        new_end = _period_end_from_start(new_start, new_mode)

    elif action == "next":
        current_month_end = today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        )
        current_end = _period_end_from_start(current_start, current_mode)
        if current_end >= current_month_end:
            # Déjà au mois courant — no-op, retourne le panel tel quel
            return budget_panel_transactions(request)
        new_mode = current_mode
        new_start = _add_months(current_start, 1)
        new_end = _period_end_from_start(new_start, new_mode)

    else:
        # Action inconnue — no-op
        return budget_panel_transactions(request)

    # Persister la nouvelle période en session
    request.session["budget_period_mode"] = new_mode
    request.session["budget_period_start"] = new_start.isoformat()
    request.session["budget_period_end"] = new_end.isoformat()

    # Retourner le fragment mis à jour (lit la session fraîchement mise à jour)
    return budget_panel_transactions(request)


# =============================================================================
# budget_toggle_ignore — Toggle is_ignored sur une transaction (POST HTMX)
# =============================================================================


@login_required
@require_POST
def budget_toggle_ignore(request, tx_id):
    """
    Bascule le flag is_ignored d'une transaction.

    URL      : POST /budget/transactions/<tx_id>/toggle-ignore/
    Source   : champ POST "source" — "list" (défaut) ou "detail"
        → "list"   : retourne budget/_panel_tx_row.html  (swap outerHTML sur #tx-id)
        → "detail" : retourne budget/_panel_tx_detail.html (swap innerHTML sur #panel-content)

    Pourquoi deux templates de retour ?
        La vue est appelée depuis deux endroits :
        1. La liste transactions (_panel_tx_row.html) — le bouton œil en hover
        2. Le panneau détail (_panel_tx_detail.html) — le toggle "Inclure dans l'analyse"
        Le champ source=detail dans le formulaire HTMX indique quel fragment retourner.
    """
    tx = get_object_or_404(
        Transaction.objects.for_user(request.user).select_related(
            "category", "subcategory", "account", "account__institution"
        ),
        pk=tx_id,
    )

    tx.is_ignored = not tx.is_ignored
    tx.save(update_fields=["is_ignored"])
    logger.debug(
        "Transaction %s: id=%s is_ignored=%s by user=%s",
        "ignored" if tx.is_ignored else "unignored",
        tx.id,
        tx.is_ignored,
        request.user.id,
    )

    bank_icon_map = _resolve_bank_icon_map()
    slug = (
        tx.account.institution.icon_slug
        if tx.account and tx.account.institution
        else ""
    )
    bank_icon_url = bank_icon_map.get(slug, "")

    # source=detail → appelé depuis les toggles du panneau détail.
    # close_on_back est passé comme champ hidden dans le formulaire pour préserver
    # le contexte (True si ouvert depuis category_detail, False sinon).
    if request.POST.get("source") == "detail":
        close_on_back = request.POST.get("close_on_back") == "true"

        if close_on_back:
            # Ouvert depuis category_detail : le panneau est posé sur une page qui
            # affiche déjà la liste + le Sankey.
            # On retourne :
            #   1. panel_html → injecté dans #panel-content (le panneau reste ouvert)
            #   2. row_html OOB → met à jour la ligne dans la liste sans reload
            #   3. cashflow_refresh_url → signal JS pour déclencher le refresh Sankey
            category_slug = tx.category.slug if tx.category else None
            cashflow_refresh_url = (
                reverse("budget:category_cashflow_fragment", args=[category_slug])
                if category_slug
                else None
            )
            panel_html = render_to_string(
                "budget/_panel_tx_detail.html",
                {
                    "tx": tx,
                    "bank_icon_url": bank_icon_url,
                    "detail_target": "#panel-content",
                    "close_on_back": True,
                    "source": "category",
                    "cashflow_refresh_url": cashflow_refresh_url,
                },
                request=request,
            )
            row_html = render_to_string(
                "budget/_panel_tx_row.html",
                {"tx": tx, "bank_icon_url": bank_icon_url, "oob": True},
                request=request,
            )
            return HttpResponse(panel_html + row_html)

        panel_html = render_to_string(
            "budget/_panel_tx_detail.html",
            {
                "tx": tx,
                "bank_icon_url": bank_icon_url,
                "detail_target": "#panel-content",
                "close_on_back": False,
                "source": "",
            },
            request=request,
        )
        return HttpResponse(panel_html)

    # source=category → appelé depuis category_detail.html.
    # On ne peut pas mettre à jour KPIs + Sankey + donut en partiel —
    # on recharge la page complète via HX-Redirect vers la même URL.
    # HTMX suit la redirection → category_detail recalcule tout avec les données fraîches.
    if request.POST.get("source") == "category":
        response = HttpResponse()
        response["HX-Redirect"] = safe_referer(request, "/budget/")
        return response

    # source=list (défaut) → appelé depuis la liste panel → retourner juste la ligne
    return render(
        request,
        "budget/_panel_tx_row.html",
        {"tx": tx, "bank_icon_url": bank_icon_url},
    )


# =============================================================================
# budget_panel_category_picker — Partial HTMX : picker catégorie (GET)
# =============================================================================


@login_required
def budget_panel_category_picker(request):
    """
    Partial HTMX — liste des catégories pour catégoriser une transaction.

    URL      : GET /budget/panel/category-picker/?tx_id=X
    Target   : #panel-content  (remplace tout le contenu du right panel)
    Template : budget/_panel_category_picker.html

    Déclenché par clic sur une ligne de transaction dans _panel_tx_row.html.

    Pourquoi deux listes séparées (system / custom) ?
        La spec Finary distingue visuellement "Catégories personnalisées" (créées
        par l'utilisateur, is_system=False) et "Catégories" (système, is_system=True).
        En Python c'est plus clair qu'un seul queryset avec groupby en template.
    """
    tx_id = request.GET.get("tx_id")
    tx = get_object_or_404(
        Transaction.objects.for_user(request.user).select_related(
            "category", "subcategory"
        ),
        pk=tx_id,
    )
    # Catégories système = seedées à l'init, non supprimables (ex: Alimentation, Transport...)
    system_cats = Category.objects.filter(is_active=True, is_system=True).order_by(
        "order"
    )
    # Catégories personnalisées = créées par l'utilisateur (aucune pour l'instant en Phase 1C)
    custom_cats = Category.objects.filter(is_active=True, is_system=False).order_by(
        "order"
    )

    source = request.GET.get("source", "")
    detail_target = "#cat-tx-detail" if source == "category" else "#panel-content"

    return render(
        request,
        "budget/_panel_category_picker.html",
        {
            "tx": tx,
            "system_cats": system_cats,
            "custom_cats": custom_cats,
            "source": source,
            "detail_target": detail_target,
        },
    )


# =============================================================================
# budget_categorize_transaction — Assigne catégorie + retourne liste (POST)
# =============================================================================


@login_required
@require_POST
def budget_categorize_transaction(request):
    """
    Assigne category + subcategory sur une transaction et retourne la liste
    des transactions pour revenir au panel état A.

    URL      : POST /budget/transactions/categorize/
    Target   : #panel-content
    Template : budget/_panel_tx_list.html  (via budget_panel_transactions)

    Pourquoi retourner budget_panel_transactions() et pas un redirect ?
        On est en HTMX — un redirect (302) serait suivi par HTMX et retournerait
        la page complète /budget/, pas le fragment. On appelle directement la vue
        fragment pour avoir le bon HTML à injecter dans #panel-content.

    HX-Trigger :
        Header HTTP custom lu par HTMX → déclenche un événement JS côté client.
        "categoryChanged" → le JS dans base_app.html affiche le toast de confirmation.
        On passe le nom de la transaction et de la catégorie pour le message du toast.
        Format : json.dumps({event_name: {payload}}) — HTMX le parse et l'émet.
    """
    tx_id = request.POST.get("tx_id")
    cat_id = request.POST.get("category_id")
    sub_id = request.POST.get("subcategory_id") or None
    source = request.POST.get("source", "")

    tx = get_object_or_404(Transaction.objects.for_user(request.user), pk=tx_id)
    tx.category = get_object_or_404(Category, pk=cat_id)
    tx.subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None
    tx.categorization_source = "manual"

    # Sync is_internal_transfer + is_ignored selon la catégorie choisie.
    # Si l'utilisateur catégorise en "Virements" → ignoré automatiquement.
    # Si changement depuis "Virements" → les deux flags repassent à False.
    extra_fields = sync_internal_transfer(tx)
    tx.save(
        update_fields=["category", "subcategory", "categorization_source"]
        + extra_fields
    )
    logger.debug(
        "Transaction categorized: id=%s category=%s subcategory=%s "
        "internal_transfer=%s by user=%s",
        tx.id,
        tx.category.slug if tx.category else None,
        tx.subcategory.slug if tx.subcategory else None,
        tx.is_internal_transfer,
        request.user.id,
    )

    # Extraction keyword + payload HX-Trigger — commun aux deux branches.
    tx_display = tx.display_name
    # Tokenize from display_name — already cleaned by _clean_description at import.
    raw_tokens = re.split(r"[\s\*\+\-\/\.\,\_]+", tx.display_name.upper())
    keyword_tokens = [
        t
        for t in raw_tokens
        if len(t) >= 3
        and not re.search(r"\d", t)
        and re.search(r"[A-Z]", t)
        and t not in RULE_NOISE_TOKENS
    ]
    keyword = keyword_tokens[0] if keyword_tokens else ""
    hx_trigger = json.dumps(
        {
            "categoryChanged": {
                "tx_name": tx_display,
                "cat_name": tx.category.name,
                "cat_id": tx.category.id,
                "tx_id": tx.id,
                "keyword": keyword,
            }
        }
    )

    # source="category" → le picker était ouvert dans l'overlay #panel-content
    # depuis category_detail.html. On retourne le détail mis à jour dans ce même
    # overlay (close_on_back=True = bouton ← ferme, pas revenir à la liste).
    if source == "category":
        tx_full = Transaction.objects.select_related(
            "category", "subcategory", "account", "account__institution"
        ).get(pk=tx.pk)
        bank_icon_map = _resolve_bank_icon_map()
        slug = (
            tx_full.account.institution.icon_slug
            if tx_full.account and tx_full.account.institution
            else ""
        )
        response = render(
            request,
            "budget/_panel_tx_detail.html",
            {
                "tx": tx_full,
                "bank_icon_url": bank_icon_map.get(slug, ""),
                "close_on_back": True,
                "source": "category",
                "detail_target": "#panel-content",
            },
        )
        response["HX-Trigger"] = hx_trigger
        return response

    # source="list" ou vide → retourner le fragment liste dans l'overlay
    response = budget_panel_transactions(request)
    response["HX-Trigger"] = hx_trigger
    return response


# =============================================================================
# budget_panel_tx_detail — Partial HTMX : détail d'une transaction (GET)
# =============================================================================


@login_required
def budget_panel_tx_detail(request):
    """
    Partial HTMX — panneau "Détails de la transaction" (état C du right panel).

    URL      : GET /budget/panel/tx-detail/?tx_id=X
    Target   : #panel-content  (remplace tout le contenu du right panel)
    Template : budget/_panel_tx_detail.html

    Déclenché par clic sur une ligne de transaction dans _panel_tx_row.html.
    Remplace l'ancien comportement qui ouvrait directement le picker catégorie.

    Pourquoi select_related avec "account__institution" ?
        On affiche le nom du compte et l'icône banque dans le panneau.
        Sans select_related, Django ferait 2 requêtes supplémentaires
        (tx → account, account → bank) au lieu d'un seul JOIN.
    """
    tx_id = request.GET.get("tx_id")
    tx = get_object_or_404(
        Transaction.objects.for_user(request.user).select_related(
            "category", "subcategory", "account", "account__institution"
        ),
        pk=tx_id,
    )

    # Résolution icône banque — même helper que les autres vues panel
    bank_icon_map = _resolve_bank_icon_map()
    slug = (
        tx.account.institution.icon_slug
        if tx.account and tx.account.institution
        else ""
    )
    bank_icon_url = bank_icon_map.get(slug, "")

    # source="category" → ouvert depuis category_detail.html.
    # close_on_back=True : bouton retour = fermer l'overlay (pas revenir à la liste,
    # qui est déjà visible dans la page principale).
    # detail_target est toujours #panel-content : l'overlay droit est utilisé partout,
    # y compris depuis category_detail. Le div #cat-tx-detail est supprimé.
    source = request.GET.get("source", "")

    return render(
        request,
        "budget/_panel_tx_detail.html",
        {
            "tx": tx,
            "bank_icon_url": bank_icon_url,
            "close_on_back": source == "category",
            "source": source,
            "detail_target": "#panel-content",
        },
    )


# =============================================================================
# budget_toggle_reconcile — Toggle is_reconciled sur une transaction (POST HTMX)
# =============================================================================


@login_required
@require_POST
def budget_toggle_reconcile(request, tx_id):
    """
    Bascule le flag is_reconciled ("Pointer la transaction") et retourne
    le panneau détail mis à jour.

    URL      : POST /budget/transactions/<tx_id>/toggle-reconcile/
    Target   : #panel-content
    Template : budget/_panel_tx_detail.html

    Pointer = vérifier que la transaction correspond au relevé de compte.
    Appelé uniquement depuis le panneau détail — pas de source à détecter.
    """
    tx = get_object_or_404(
        Transaction.objects.for_user(request.user).select_related(
            "category", "subcategory", "account", "account__institution"
        ),
        pk=tx_id,
    )

    tx.is_reconciled = not tx.is_reconciled
    tx.save(update_fields=["is_reconciled"])
    logger.debug(
        "Transaction %s: id=%s is_reconciled=%s by user=%s",
        "reconciled" if tx.is_reconciled else "unreconciled",
        tx.id,
        tx.is_reconciled,
        request.user.id,
    )

    bank_icon_map = _resolve_bank_icon_map()
    slug = (
        tx.account.institution.icon_slug
        if tx.account and tx.account.institution
        else ""
    )
    bank_icon_url = bank_icon_map.get(slug, "")

    # source=list → appelé depuis la ligne liste → retourner juste la ligne
    if request.POST.get("source") != "detail":
        return render(
            request,
            "budget/_panel_tx_row.html",
            {"tx": tx, "bank_icon_url": bank_icon_url},
        )

    # source=detail → retourner le panneau entier mis à jour.
    close_on_back = request.POST.get("close_on_back") == "true"
    if close_on_back:
        # Ouvert depuis category_detail : panneau reste ouvert, ligne liste à jour.
        # is_reconciled ne modifie pas les totaux → pas de cashflow_refresh_url.
        panel_html = render_to_string(
            "budget/_panel_tx_detail.html",
            {
                "tx": tx,
                "bank_icon_url": bank_icon_url,
                "detail_target": "#panel-content",
                "close_on_back": True,
                "source": "category",
            },
            request=request,
        )
        row_html = render_to_string(
            "budget/_panel_tx_row.html",
            {"tx": tx, "bank_icon_url": bank_icon_url, "oob": True},
            request=request,
        )
        return HttpResponse(panel_html + row_html)
    return render(
        request,
        "budget/_panel_tx_detail.html",
        {
            "tx": tx,
            "bank_icon_url": bank_icon_url,
            "detail_target": "#panel-content",
            "close_on_back": False,
            "source": "",
        },
    )

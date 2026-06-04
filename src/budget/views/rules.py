"""
budget/views_rules.py — Vues CRUD des règles de catégorisation.

Contient le wizard de création de règle (transaction-first + standalone),
les previews live, et le panel CRUD (liste, toggle, delete, edit).
"""

import logging
import re
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.constants import RULE_NOISE_TOKENS
from budget.utils import _cats_with_subcats, _keyword_q, _resolve_bank_icon_map
from transactions.models import CategorizationRule, Category, SubCategory, Transaction

logger = logging.getLogger(__name__)

# =============================================================================
# budget_modal_rule_intro — Modal step 1 : "Appliquer [cat] aux transactions similaires"
# =============================================================================


@login_required
def budget_modal_rule_intro(request):
    """
    Modal HTMX — étape 1 du wizard règle intelligente.

    URL    : GET /budget/modal/rule-intro/?tx_id=X&keyword=Y
    Target : #modal-content (ouverture automatique via body listener htmx:afterSwap)

    Affiche :
      - La transaction source (nom + montant + icône catégorie)
      - "Appliquer [catégorie] aux transactions similaires"
      - Boutons : "Plus tard" (closeModal) | "Suivant" → étape 2 (keyword chips)

    La catégorie est lue depuis tx.category — déjà mise à jour par
    budget_categorize_transaction avant que le toast n'apparaisse.
    """
    tx_id = request.GET.get("tx_id")
    keyword = request.GET.get("keyword", "")

    tx = get_object_or_404(
        Transaction.objects.for_user(request.user).select_related(
            "category", "subcategory"
        ),
        pk=tx_id,
    )

    return render(
        request,
        "budget/_modal_rule_intro.html",
        {
            "tx": tx,
            "category": tx.category,
            "subcategory": tx.subcategory,
            "keyword": keyword,
        },
    )


# =============================================================================
# budget_panel_rule_create — Partial HTMX : formulaire création règle (GET)
# =============================================================================


@login_required
def budget_panel_rule_create(request):
    """
    Partial HTMX — panneau "Créer une règle intelligente".

    URL      : GET /budget/panel/rule-create/?tx_id=X&keyword=MIGROS
    Target   : #panel-content
    Template : budget/_panel_rule_create.html

    Déclenché par le bouton "Créer une règle automatique →" dans le toast,
    après qu'une transaction a été catégorisée manuellement.

    Contexte transmis au template :
        tx       — Transaction source (pour afficher son nom + catégorie actuelle)
        keyword  — Token pré-rempli extrait de description_raw (ex: "MIGROS")
        categories — QuerySet Category actives triées par order (pour le dropdown)
    """
    tx_id = request.GET.get("tx_id")
    keyword = request.GET.get("keyword", "").strip()
    cat_id = request.GET.get("cat_id")
    subcat_id = request.GET.get("subcat_id")

    tx = get_object_or_404(
        Transaction.objects.for_user(request.user).select_related(
            "category", "subcategory"
        ),
        pk=tx_id,
    )

    # Catégorie cible : passée explicitement depuis l'étape intro, ou fallback sur tx.category.
    category = get_object_or_404(Category, pk=cat_id) if cat_id else tx.category
    subcategory = None
    if subcat_id:
        subcategory = SubCategory.objects.filter(pk=subcat_id).first()
    elif tx.subcategory:
        subcategory = tx.subcategory

    # Tokens cliquables depuis display_name — déjà nettoyé par _clean_description à l'import.
    # Filtre agressif : on garde seulement les tokens qui ont une valeur sémantique
    # (nom de commerce, lieu…) et on écarte le bruit banque (RULE_NOISE_TOKENS).
    raw_tokens = re.split(r"[\s\*\+\-\/\.\,\_]+", tx.display_name.upper())
    seen = set()
    tokens = []
    for t in raw_tokens:
        if (
            len(t) >= 3  # trop court → bruit
            and not re.search(
                r"\d", t
            )  # aucun chiffre → exclut codes type ESSOF108, B560945
            and re.search(r"[A-Z]", t)  # doit contenir au moins une lettre
            and t not in RULE_NOISE_TOKENS  # liste noire métadonnées banque
            and t not in seen
        ):
            seen.add(t)
            tokens.append(t)

    # Aperçu initial des transactions correspondant au keyword suggéré.
    # Rechargé via HTMX (budget_rule_live_preview) à chaque clic de chip.
    initial_txs = []
    initial_count = 0
    if keyword:
        qs = (
            Transaction.objects.for_user(request.user)
            .filter(_keyword_q(keyword))
            .select_related("subcategory")
            .order_by("-date")
        )
        initial_count = qs.count()
        initial_txs = list(qs)  # toutes les transactions — la zone est scrollable

    cat_display_name = (
        subcategory.name if subcategory else (category.name if category else "")
    )

    return render(
        request,
        "budget/_panel_rule_create.html",
        {
            "tx": tx,
            "keyword": keyword,
            "tokens": tokens,
            "category": category,
            "subcategory": subcategory,
            "cat_display_name": cat_display_name,
            "initial_txs": initial_txs,
            "initial_count": initial_count,
        },
    )


# =============================================================================
# budget_panel_rule_create_standalone — Formulaire création règle sans source tx
# =============================================================================


@login_required
def budget_panel_rule_create_standalone(request):
    """
    Partial HTMX — panneau "Créer une règle intelligente" en mode standalone.

    URL      : GET /budget/panel/rule-create-standalone/
    Target   : #modal-content
    Template : budget/_panel_rule_create_standalone.html

    Déclenché depuis le dropdown "Créer" → bouton "Nouvelle règle intelligente".
    Contrairement à budget_panel_rule_create, aucun tx_id n'est requis.
    L'utilisateur saisit le keyword manuellement et choisit la catégorie.

    Différence clé avec le wizard transaction-first :
        - Pas de tx source → pas de chips extraits d'une description
        - Keyword libre (input texte) → même live preview via rule_live_preview
        - Picker catégorie identique à _rule_row_edit.html (réutilise ruleEditSelect)
        - Submit → budget_rule_create_submit (même vue, même payload)
    """
    _, cats_with_subcats = _cats_with_subcats()
    return render(
        request,
        "budget/_panel_rule_create_standalone.html",
        {
            "cats_with_subcats": cats_with_subcats,
        },
    )


# =============================================================================
# budget_rule_standalone_preview — Preview multi-chips (GET HTMX)
# =============================================================================


@login_required
def budget_rule_standalone_preview(request):
    r"""
    Partial HTMX — aperçu des transactions matchant un keyword composé.

    URL      : GET /budget/panel/rule-standalone-preview/?kw=MIGROS&kw=CAROUGE&category_id=5
    Target   : #rule-preview-zone
    Template : budget/_rule_standalone_preview.html

    Les chips du formulaire standalone s'accumulent en AND :
        kw=MIGROS            → transactions contenant "MIGROS"
        kw=MIGROS&kw=CAROUGE → transactions contenant "MIGROS" ET "CAROUGE"

    L'opérateur AND est géré par _keyword_q(combined) : les mots sont séparés par
    un espace et chacun est matché comme word boundary (\y) dans description_raw.
    Même règle que la catégorisation automatique à l'import — cohérence garantie.

    La vue résout les icônes banque (bank_icon_map) pour la rangée compacte,
    charge les 25 premières transactions pour la preview scrollable.
    """
    kw_list = [kw.strip().upper() for kw in request.GET.getlist("kw") if kw.strip()]
    cat_id = request.GET.get("category_id")
    subcat_id = request.GET.get("subcategory_id")

    # Keyword composé : "MIGROS CAROUGE" → _keyword_q AND-e les deux mots
    combined_keyword = " ".join(kw_list)

    cat_display_name = ""
    if cat_id:
        cat = Category.objects.filter(pk=cat_id).first()
        if cat:
            sub = (
                SubCategory.objects.filter(pk=subcat_id).first() if subcat_id else None
            )
            cat_display_name = sub.name if sub else cat.name

    txs = []
    total_count = 0

    if combined_keyword:
        qs = (
            Transaction.objects.for_user(request.user)
            .filter(_keyword_q(combined_keyword))
            .select_related(
                "account", "account__institution", "category", "subcategory"
            )
            .order_by("-date")
        )
        total_count = qs.count()
        # On charge toutes les tx pour la zone scrollable (limit visuelle = template)
        txs = list(qs)
        bank_icon_map = _resolve_bank_icon_map()
        for tx in txs:
            slug = (
                tx.account.institution.icon_slug
                if tx.account and tx.account.institution
                else ""
            )
            tx.bank_icon_url = bank_icon_map.get(slug, "")

    return render(
        request,
        "budget/_rule_standalone_preview.html",
        {
            "txs": txs,
            "total_count": total_count,
            "kw_list": kw_list,
            "combined_keyword": combined_keyword,
            "cat_display_name": cat_display_name,
        },
    )


# =============================================================================
# budget_rule_create_standalone_submit — Crée 1 règle composée + bulk apply (POST)
# =============================================================================


@login_required
@require_POST
def budget_rule_create_standalone_submit(request):
    """
    Crée une CategorizationRule avec keyword composé + bulk apply.

    URL      : POST /budget/transactions/rule-create-standalone/
    Target   : #modal-content

    Flow en deux étapes si des transactions seront écrasées :
        Étape 1 (force absent) :
            - Vérifie si des transactions ont déjà une règle différente → keyword
            - Si oui : retourne _panel_rule_overwrite_warning.html (SANS créer la règle)
            - Si non : passe directement à l'étape 2
        Étape 2 (force=1 dans POST) :
            - Crée la règle + bulk apply → _panel_rule_confirm.html (succès)

    Le keyword composé est transmis en deux variantes :
        - Chips initiales : POST multi-value kw[] = ["MIGROS", "CAROUGE"]
        - Re-confirmation après warning : POST single keyword = "MIGROS CAROUGE"
    La vue accepte les deux — keyword single prend priorité.
    """
    # Accepte soit un keyword déjà joint (re-confirmation) soit des chips kw[]
    keyword_single = request.POST.get("keyword", "").strip().upper()
    if keyword_single:
        keyword = keyword_single
    else:
        kw_list = [
            kw.strip().upper() for kw in request.POST.getlist("kw") if kw.strip()
        ]
        if not kw_list:
            return HttpResponseBadRequest("Au moins un mot-clé requis")
        keyword = " ".join(kw_list)

    cat_id = request.POST.get("category_id")
    sub_id = request.POST.get("subcategory_id") or None
    force = request.POST.get("force") == "1"

    category = get_object_or_404(Category, pk=cat_id)
    subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None

    if not force:
        # Étape 1 — chercher les transactions qui seront écrasées AVANT de créer la règle.
        # On vérifie les tx avec source="rule" et une règle différente de celle qu'on va créer.
        # existing_rule peut être None si la règle n'existe pas encore.
        existing_rule = CategorizationRule.objects.filter(
            keyword=keyword, category=category
        ).first()
        overwrite_qs = Transaction.objects.for_user(request.user).filter(
            _keyword_q(keyword), categorization_source="rule"
        )
        if existing_rule:
            overwrite_qs = overwrite_qs.exclude(categorization_rule=existing_rule)

        if overwrite_qs.exists():
            txs = list(
                overwrite_qs.select_related(
                    "account", "account__institution", "category", "subcategory"
                ).order_by("-date")
            )
            bank_icon_map = _resolve_bank_icon_map()
            for tx in txs:
                slug = (
                    tx.account.institution.icon_slug
                    if tx.account and tx.account.institution
                    else ""
                )
                tx.bank_icon_url = bank_icon_map.get(slug, "")

            return render(
                request,
                "budget/_panel_rule_overwrite_warning.html",
                {
                    "txs": txs,
                    "overwritten_count": len(txs),
                    "keyword": keyword,
                    "category": category,
                    "subcategory": subcategory,
                    "form_action": reverse("budget:rule_create_standalone_submit"),
                },
            )

    # Étape 2 — créer la règle + bulk apply
    # Priorité = max existant + 1 → la dernière règle créée gagne toujours en cas de conflit
    next_priority = (
        CategorizationRule.objects.aggregate(m=Max("priority"))["m"] or 0
    ) + 1
    rule, created = CategorizationRule.objects.get_or_create(
        keyword=keyword,
        category=category,
        defaults={
            "subcategory": subcategory,
            "target_field": "display_name",
            "priority": next_priority,
            "is_active": True,
        },
    )

    updated_count = (
        Transaction.objects.for_user(request.user)
        .filter(_keyword_q(keyword))
        .update(
            category=category,
            subcategory=subcategory,
            categorization_source="rule",
            categorization_rule=rule,
        )
    )

    log = logger.info if created else logger.debug
    log(
        "CategorizationRule %s: id=%s keyword=%r cat=%s applied to %d tx by user=%s",
        "created" if created else "reused",
        rule.id,
        keyword,
        category.slug,
        updated_count,
        request.user.id,
    )

    return render(
        request,
        "budget/_panel_rule_confirm.html",
        {
            "rule": rule,
            "created": created,
            "updated_count": updated_count,
            "keyword": keyword,
            "category": category,
            "subcategory": subcategory,
        },
    )


# =============================================================================
# budget_rule_live_preview — Partial HTMX : liste live des transactions matchées
# =============================================================================


@login_required
def budget_rule_live_preview(request):
    """
    GET → retourne la liste des transactions dont description_raw contient le keyword.

    URL    : GET /budget/transactions/rule-live-preview/?keyword=X&category_id=Y
    Target : #rule-preview-zone (dans _panel_rule_create.html)

    Déclenché à chaque changement de chip dans le wizard règle.
    Retourne un fragment HTML (pas une page complète).
    """
    keyword = request.GET.get("keyword", "").strip().upper()
    cat_id = request.GET.get("category_id")

    cat_display_name = ""
    if cat_id:
        cat = Category.objects.filter(pk=cat_id).first()
        if cat:
            # Si une sous-catégorie est passée, on l'affiche en priorité
            subcat_id = request.GET.get("subcategory_id")
            if subcat_id:
                sub = SubCategory.objects.filter(pk=subcat_id).first()
                cat_display_name = sub.name if sub else cat.name
            else:
                cat_display_name = cat.name

    txs = []
    count = 0
    if keyword:
        qs = (
            Transaction.objects.for_user(request.user)
            .filter(_keyword_q(keyword))
            .order_by("-date")
        )
        count = qs.count()
        txs = list(qs)  # toutes les transactions — la zone est scrollable

    return render(
        request,
        "budget/_rule_live_preview.html",
        {
            "txs": txs,
            "count": count,
            "keyword": keyword,
            "cat_display_name": cat_display_name,
        },
    )


# =============================================================================
# budget_rule_preview — Prévisualise la règle sans l'appliquer (POST)
# =============================================================================


@login_required
@require_POST
def budget_rule_preview(request):
    """
    Prévisualise l'impact d'une règle sans rien créer ni modifier en DB.

    URL      : POST /budget/transactions/rule-preview/
    Target   : #panel-content
    Template : budget/_panel_rule_preview.html

    Reçoit keyword + category_id + subcategory_id + tx_id.
    Compte le nombre de transactions qui seraient affectées (icontains, exclude manual).
    Retourne un panel avec le résumé de la règle + le count + un bouton Valider.

    Pourquoi POST et pas GET ?
        Les données (keyword, category_id) viennent d'un formulaire HTMX.
        GET avec ces données nécessiterait de construire une URL à la main en JS.
        POST est plus simple et cohérent avec les autres actions du panel.
    """
    keyword = request.POST.get("keyword", "").strip().upper()
    cat_id = request.POST.get("category_id")
    sub_id = request.POST.get("subcategory_id") or None
    tx_id = request.POST.get("tx_id")

    if tx_id:
        get_object_or_404(Transaction.objects.for_user(request.user), pk=tx_id)

    category = get_object_or_404(Category, pk=cat_id)
    subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None

    # Compter les transactions affectées SANS les modifier.
    # Toutes les transactions matchant le keyword sont comptées — sans exclusion.
    # Une règle explicite doit pouvoir écraser toute catégorisation antérieure.
    affected_count = (
        Transaction.objects.for_user(request.user).filter(_keyword_q(keyword)).count()
    )

    return render(
        request,
        "budget/_panel_rule_preview.html",
        {
            "keyword": keyword,
            "category": category,
            "subcategory": subcategory,
            "tx_id": tx_id,
            "affected_count": affected_count,
        },
    )


# =============================================================================
# budget_rule_create_submit — Crée la règle + bulk apply (POST)
# =============================================================================


@login_required
@require_POST
def budget_rule_create_submit(request):
    """
    Crée une CategorizationRule et l'applique aux transactions existantes.

    URL      : POST /budget/transactions/rule-create/
    Target   : #panel-content
    Template : budget/_panel_rule_confirm.html

    Étapes :
        1. Lire keyword + category_id + subcategory_id depuis POST
        2. Créer (ou récupérer si doublon) la CategorizationRule
        3. Bulk update : appliquer aux transactions dont description_raw
           contient le keyword — sauf celles catégorisées manuellement
           (categorization_source="manual" = choix explicite de l'user → jamais écrasé)
        4. Retourner le panel de confirmation avec le count mis à jour

    Pourquoi exclure categorization_source="manual" ?
        Si l'user a déjà catégorisé une transaction à la main, c'est une décision
        intentionnelle. On ne doit pas l'écraser avec une règle automatique.
        Seules les transactions "default" (import), "rule" (autre règle) ou
        "ai" (Claude) sont recatégorisables.
    """
    keyword = request.POST.get("keyword", "").strip().upper()
    cat_id = request.POST.get("category_id")
    sub_id = request.POST.get("subcategory_id") or None
    tx_id = request.POST.get("tx_id")
    force = request.POST.get("force") == "1"

    if not keyword:
        return HttpResponseBadRequest("keyword requis")

    category = get_object_or_404(Category, pk=cat_id)
    subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None

    if not force:
        # Étape 1 — vérifier les transactions déjà catégorisées par UNE AUTRE règle.
        existing_rule = CategorizationRule.objects.filter(
            keyword=keyword, category=category
        ).first()
        overwrite_qs = Transaction.objects.for_user(request.user).filter(
            _keyword_q(keyword), categorization_source="rule"
        )
        if existing_rule:
            overwrite_qs = overwrite_qs.exclude(categorization_rule=existing_rule)

        if overwrite_qs.exists():
            txs = list(
                overwrite_qs.select_related(
                    "account", "account__institution", "category", "subcategory"
                ).order_by("-date")
            )
            bank_icon_map = _resolve_bank_icon_map()
            for tx in txs:
                slug = (
                    tx.account.institution.icon_slug
                    if tx.account and tx.account.institution
                    else ""
                )
                tx.bank_icon_url = bank_icon_map.get(slug, "")

            return render(
                request,
                "budget/_panel_rule_overwrite_warning.html",
                {
                    "txs": txs,
                    "overwritten_count": len(txs),
                    "keyword": keyword,
                    "category": category,
                    "subcategory": subcategory,
                    "tx_id": tx_id,
                    "form_action": reverse("budget:rule_create_submit"),
                },
            )

    # Étape 2 — créer la règle + bulk apply
    next_priority = (
        CategorizationRule.objects.aggregate(m=Max("priority"))["m"] or 0
    ) + 1
    rule, created = CategorizationRule.objects.get_or_create(
        keyword=keyword,
        category=category,
        defaults={
            "subcategory": subcategory,
            "target_field": "display_name",
            "priority": next_priority,
            "is_active": True,
        },
    )

    updated_count = (
        Transaction.objects.for_user(request.user)
        .filter(
            _keyword_q(keyword),
        )
        .update(
            category=category,
            subcategory=subcategory,
            categorization_source="rule",
            categorization_rule=rule,
        )
    )

    return render(
        request,
        "budget/_panel_rule_confirm.html",
        {
            "rule": rule,
            "created": created,
            "updated_count": updated_count,
            "keyword": keyword,
            "category": category,
            "subcategory": subcategory,
        },
    )


# =============================================================================
# budget_export_rules_download — Télécharge les règles de catégorisation en JSON
# =============================================================================


@login_required
def budget_export_rules_download(request):
    """
    Retourne toutes les CategorizationRule (actives ET inactives) en JSON téléchargeable.

    URL : /budget/export/rules/
    Response : application/json avec Content-Disposition: attachment

    Format du fichier (identique à la management command export_rules) :
        {
            "exported_at": "YYYY-MM-DD",
            "count": N,
            "rules": [
                {"keyword": "...", "category_slug": "...", "subcategory_slug": "...",
                 "target_field": "...", "priority": N, "is_active": true},
                ...
            ]
        }

    Pourquoi exporter via le navigateur et pas seulement via make export-rules ?
        - Accessible depuis l'UI sans ouvrir un terminal.
        - Utile avant la session de classification manuelle pour faire un backup rapide.
    """
    rules = list(
        CategorizationRule.objects.all()
        .values(
            "keyword",
            "category__slug",
            "subcategory__slug",
            "target_field",
            "priority",
            "is_active",
        )
        .order_by("priority", "keyword")
    )

    # Renommer les clés pour un JSON lisible (category__slug → category_slug)
    clean_rules = [
        {
            "keyword": r["keyword"],
            "category_slug": r["category__slug"],
            "subcategory_slug": r["subcategory__slug"],
            "target_field": r["target_field"],
            "priority": r["priority"],
            "is_active": r["is_active"],
        }
        for r in rules
    ]

    data = {
        "exported_at": str(date.today()),
        "count": len(clean_rules),
        "rules": clean_rules,
    }

    filename = f"rules_{date.today()}.json"
    response = JsonResponse(
        data, json_dumps_params={"indent": 2, "ensure_ascii": False}
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# =============================================================================
# budget_panel_rules_list — Panel CRUD des règles de catégorisation (GET)
# =============================================================================


@login_required
def budget_panel_rules_list(request):
    """
    Charge le panel de gestion des règles dans #modal-content.

    URL : GET /budget/panel/rules/
    Cible HTMX : #modal-content (openModal() déclenché automatiquement par base_app.html)

    Affiche toutes les règles triées : actives d'abord, puis par priorité desc, puis keyword.
    """
    rules = CategorizationRule.objects.select_related(
        "category", "subcategory__category"
    ).order_by("-is_active", "-priority", "keyword")

    all_categories, cats_with_subcats = _cats_with_subcats()

    return render(
        request,
        "budget/_panel_rules_list.html",
        {
            "rules": rules,
            "all_categories": all_categories,
            "cats_with_subcats": cats_with_subcats,
        },
    )


# =============================================================================
# budget_rule_toggle_active — Toggle is_active sur une règle (POST HTMX)
# =============================================================================


@login_required
@require_POST
def budget_rule_toggle_active(request, rule_id):
    """
    Inverse is_active d'une règle et retourne la ligne mise à jour.

    URL : POST /budget/rules/<rule_id>/toggle/
    HTMX : hx-target="#rule-<id>" hx-swap="outerHTML"
    """
    rule = get_object_or_404(CategorizationRule, id=rule_id)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active"])
    return render(request, "budget/_rule_row.html", {"rule": rule})


# =============================================================================
# budget_rule_delete — Supprime une règle (POST HTMX)
# =============================================================================


@login_required
@require_POST
def budget_rule_delete(request, rule_id):
    """
    Supprime la règle et retourne une réponse vide → HTMX retire la ligne du DOM.

    URL : POST /budget/rules/<rule_id>/delete/
    HTMX : hx-target="#rule-<id>" hx-swap="outerHTML"
           hx-confirm="Supprimer ?" (confirmation navigateur native)
    """
    rule = get_object_or_404(CategorizationRule, id=rule_id)
    logger.info(
        "CategorizationRule deleted: id=%s keyword=%r by user=%s",
        rule.id,
        rule.keyword,
        request.user.id,
    )
    rule.delete()
    return HttpResponse("")


# =============================================================================
# budget_rule_row_edit — Retourne la ligne en mode édition (GET HTMX)
# =============================================================================


@login_required
def budget_rule_row_edit(request, rule_id):
    """
    Remplace la ligne de lecture par un formulaire d'édition inline.

    URL : GET /budget/rules/<rule_id>/edit/
    HTMX : hx-target="#rule-<id>" hx-swap="outerHTML"

    ?cancel=1 → retourne la ligne en mode lecture (bouton Annuler du formulaire).
    """
    rule = get_object_or_404(CategorizationRule, id=rule_id)
    if request.GET.get("cancel"):
        return render(request, "budget/_rule_row.html", {"rule": rule})
    all_categories, cats_with_subcats = _cats_with_subcats()
    return render(
        request,
        "budget/_rule_row_edit.html",
        {
            "rule": rule,
            "all_categories": all_categories,
            "cats_with_subcats": cats_with_subcats,
        },
    )


# =============================================================================
# budget_rule_edit_submit — Sauvegarde les modifications d'une règle (POST HTMX)
# =============================================================================


@login_required
@require_POST
def budget_rule_edit_submit(request, rule_id):
    """
    Valide et sauvegarde keyword + category + subcategory d'une règle.
    Retourne la ligne en mode lecture avec les nouvelles valeurs.

    URL : POST /budget/rules/<rule_id>/edit/
    HTMX : hx-target="#rule-<id>" hx-swap="outerHTML"

    keyword est normalisé en UPPERCASE (cohérence avec le wizard de création).
    Si keyword ou category_id manquent, la règle est retournée inchangée.
    """
    rule = get_object_or_404(CategorizationRule, id=rule_id)
    keyword = request.POST.get("keyword", "").strip().upper()
    category_id = request.POST.get("category_id", "").strip()
    subcategory_id = request.POST.get("subcategory_id", "").strip() or None

    if keyword and category_id:
        try:
            cat_id = int(category_id)
            subcat_id = int(subcategory_id) if subcategory_id else None
        except (ValueError, TypeError):
            # category_id non numérique → ignorer silencieusement, retourner la règle inchangée
            return render(request, "budget/_rule_row.html", {"rule": rule})
        rule.keyword = keyword
        rule.category_id = cat_id
        rule.subcategory_id = subcat_id
        rule.save(update_fields=["keyword", "category_id", "subcategory_id"])

    return render(request, "budget/_rule_row.html", {"rule": rule})

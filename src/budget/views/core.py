"""
budget/views.py — Vues core de l'application Budget.

Contient uniquement les vues principales :
    - budget_index (page Budget principale)
    - Navigation temporelle (set_period, set_period_month)
    - Onglets (set_tab, set_cat_tab)
    - Filtres session (toggle_filter_account, toggle_filter_category)
    - Paramètres (toggle_decimals)

Vues déplacées dans des modules dédiés :
    - views_transactions.py : panneau transactions + catégorisation
    - views_rules.py        : CRUD règles de catégorisation
    - views_categories.py   : détail + gestion des catégories
    - utils.py              : helpers partagés (période, icônes, etc.)
    - constants.py          : constantes métier

Pourquoi tout en session Django ?
    → Décision d'archi 2026-04-01 : pas d'URL params pour l'état UI.
    Chaque requête POST/HTMX met à jour la session, puis redirige (ou re-render)
    en GET pour que le navigateur voie toujours une URL propre.
"""

import calendar
import logging
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Account
from budget.constants import (
    MOIS_FR,
    PERIOD_MODE_MONTHS,
)
from budget.utils import (
    _add_months,
    _gradient,
    _period_end_from_start,
    _period_from_session,
    safe_referer,
)
from budget.views.transactions import budget_panel_transactions
from transactions.models import (
    BudgetTarget,
    Category,
    Transaction,
)

logger = logging.getLogger(__name__)


# =============================================================================
# budget_index — Page Budget principale
# =============================================================================


@login_required
def budget_index(request):
    """
    Page Budget : agrégation des transactions par catégorie pour la période active.

    URL : /budget/
    Template : budget/index.html

    Ce que cette vue calcule :
        - La période active (mois en cours par défaut)
        - Les 3 KPIs : Entrées totales / Sorties totales / Dépenses récurrentes
        - Les catégories de dépenses triées par montant décroissant
        - Les catégories de revenus triées par montant décroissant
        - La répartition en % pour le donut

    Principe des sessions Django :
        request.session est un dict persisté côté serveur (table django_session en DB).
        Chaque utilisateur a sa propre session. On y stocke l'état UI pour qu'il
        survive entre les requêtes GET. Le navigateur envoie juste un cookie de session.
    """

    # ── 1. Période active ─────────────────────────────────────────────────────
    #
    # On stocke en session le premier et le dernier jour du mois actif.
    # Format : "YYYY-MM-DD" (string ISO) — simple à sérialiser en JSON (format session).
    #
    # Default : mois en cours.
    # "calendar.monthrange(year, month)[1]" retourne le nombre de jours dans le mois.
    # Ex: monthrange(2026, 2)[1] → 28 (ou 29 si bissextile)

    today = date.today()

    period_start, period_end = _period_from_session(request.session)
    if not request.session.get("budget_period_start"):
        request.session["budget_period_start"] = period_start.isoformat()
        request.session["budget_period_end"] = period_end.isoformat()

    # Mode actif : "1m" | "3m" | "1y" — stocké en session, défaut 1 mois
    period_mode = request.session.get("budget_period_mode", "1m")

    # Label affiché dans la topbar : "Mars 2026" (1M) ou "Mars — Juin 2026" (3M)
    # MOIS_FR est défini au niveau module (partagé avec budget_set_period)
    if period_mode == "1m":
        period_label = f"{MOIS_FR[period_start.month]} {period_start.year}"
    else:
        period_label = (
            f"{MOIS_FR[period_start.month]} — "
            f"{MOIS_FR[period_end.month]} {period_end.year}"
        )

    # ── 2. Onglet actif ───────────────────────────────────────────────────────
    #
    # 3 onglets dans l'UI Budget : sorties | entrees | recurrentes
    # Stocké en session. Default : "sorties".
    active_tab = request.session.get("budget_active_tab", "sorties")

    # ── 2b. Filtres multi-select actifs ──────────────────────────────────────
    #
    # Deux filtres stockés en session (vide = pas de filtre = tout afficher) :
    #   budget_filter_accounts          → list[int]  : IDs des comptes sélectionnés
    #   budget_filter_categories_hidden → list[str]  : slugs des catégories MASQUÉES (blacklist)
    #
    # Blacklist catégories : vide = tout afficher, non-vide = exclure ces slugs.
    # Tous les cercles sont dorés par défaut (= tout visible). Cliquer masque (exclut).
    #
    # On charge aussi les données pour les dropdowns du template :
    #   accounts       → tous les comptes actifs (pour le sélecteur "Tous les comptes")
    #   all_categories → toutes les catégories actives (pour le sélecteur catégories)
    filter_account_ids = request.session.get("budget_filter_accounts_hidden", [])
    hidden_cat_slugs = request.session.get("budget_filter_categories_hidden", [])
    accounts = (
        Account.objects.for_user(request.user)
        .filter(is_active=True)
        .select_related("institution")
        .order_by("institution__name", "name")
    )
    all_categories = (
        Category.objects.for_user(request.user)
        .filter(is_active=True)
        .order_by("order", "name")
    )

    # ── 3. Queryset de base ───────────────────────────────────────────────────
    #
    # Les transactions exclues systématiquement du budget :
    #   - is_ignored=True : l'utilisateur a coché "Exclure de l'analyse"
    #   - is_internal_transfer=True : virement entre propres comptes (ex: Yuh → CIC)
    #     Ces virements gonfleraient artificiellement sorties ET entrées.
    #   - category__isnull=True : transactions sans catégorie → on les met dans
    #     la catégorie "Inconnu". Si on les filtre ici, elles disparaissent du budget.
    #     On les INCLUT donc — l'Inconnu apparaîtra comme une catégorie normale.
    #
    # .filter() retourne un QuerySet (objet lazy) — la requête SQL n'est pas encore
    # envoyée à PostgreSQL. Elle le sera seulement quand on itère ou qu'on appelle
    # .aggregate(), .annotate()...
    # for_user() : filtre de sécurité — seules les tx des comptes dont
    # request.user est membre. Sans ce filtre, un autre user connecté verrait tout.
    qs = Transaction.objects.for_user(request.user).filter(
        date__gte=period_start,
        date__lte=period_end,
        is_ignored=False,
        is_internal_transfer=False,
    )
    # Appliquer les filtres multi-select si actifs (vide = tout afficher, blacklist)
    if filter_account_ids:
        qs = qs.exclude(account_id__in=filter_account_ids)
    if hidden_cat_slugs:
        qs = qs.exclude(category__slug__in=hidden_cat_slugs)

    # ── 4. KPIs ───────────────────────────────────────────────────────────────
    #
    # Django .aggregate() exécute UNE requête SQL et retourne un dict.
    # Ex: {"total": Decimal('-2341.50')} ou {"total": None} si aucune transaction.
    #
    # Entrées = montants positifs (salaire, remboursements, cadeaux...)
    # Sorties = montants négatifs (dépenses) — on garde le signe, on l'affiche abs()
    # Récurrentes = dépenses marquées is_recurring=True (loyer, abo...)

    total_income = (
        qs.filter(amount__gt=0).aggregate(total=Sum(Coalesce("amount_chf", "amount")))[
            "total"
        ]
        or 0
    )

    total_expenses = (
        qs.filter(amount__lt=0).aggregate(total=Sum(Coalesce("amount_chf", "amount")))[
            "total"
        ]
        or 0
    )

    total_recurring = (
        qs.filter(amount__lt=0, is_recurring=True).aggregate(
            total=Sum(Coalesce("amount_chf", "amount"))
        )["total"]
        or 0
    )

    # ── 5. Agrégation par catégorie ───────────────────────────────────────────
    #
    # .values() + .annotate() = GROUP BY en SQL.
    # Traduction SQL approximative :
    #   SELECT category_id, category__name, SUM(amount) as total
    #   FROM transactions
    #   WHERE date BETWEEN ... AND ... AND is_ignored=False AND ...
    #   GROUP BY category_id, category__name, ...
    #   ORDER BY category__order
    #
    # Résultat : une liste de dicts, un dict par catégorie.
    # Ex: [{"category__name": "Alimentation", "total": Decimal("-234.50"), ...}, ...]
    #
    # Pourquoi category__isnull=False ici ?
    #   On INCLUT les transactions sans catégorie dans le qs de base (voir § 3).
    #   Mais on ne peut pas les grouper par catégorie si elle est NULL.
    #   On les exclut de l'agrégation catégorie → elles n'apparaissent pas dans les listes.
    #   Elles comptent quand même dans les KPIs (total_income/expenses ci-dessus).
    cat_totals = (
        qs.filter(category__isnull=False)
        .values(
            "category__id",
            "category__name",
            "category__slug",
            "category__colour_hex",
            "category__icon",
            "category__order",
        )
        .annotate(total=Sum(Coalesce("amount_chf", "amount")))
        .order_by("category__order")
    )

    # ── 6. Split entrées / sorties ────────────────────────────────────────────
    #
    # On sépare en Python (pas en SQL) pour garder les requêtes simples.
    # Un "total > 0" sur une catégorie de dépenses est théoriquement possible
    # (ex: remboursement reçu sur une catégorie Alimentation) → on classe par signe.
    #
    # Tri :
    #   expense_categories    : du plus gros poste au plus petit (le plus négatif en premier)
    #   income_categories     : du plus grand revenu au plus petit
    #   recurring_categories  : même logique que expense, mais seulement is_recurring=True
    expense_categories = sorted(
        [c for c in cat_totals if c["total"] < 0],
        key=lambda c: c["total"],  # -2000 < -500 → -2000 en premier
    )

    income_categories = sorted(
        [c for c in cat_totals if c["total"] > 0],
        key=lambda c: -c["total"],  # 3500 > 500 → 3500 en premier
    )

    # Catégories récurrentes : même GROUP BY que cat_totals mais filtré sur is_recurring.
    # Requête séparée (pas un filtre sur cat_totals) car cat_totals est déjà évalué.
    # On recalcule les pct plus bas, dans le bloc donut.
    recurring_cat_totals = (
        qs.filter(category__isnull=False, amount__lt=0, is_recurring=True)
        .values(
            "category__id",
            "category__name",
            "category__slug",
            "category__colour_hex",
            "category__icon",
            "category__order",
        )
        .annotate(total=Sum(Coalesce("amount_chf", "amount")))
        .order_by("category__order")
    )
    recurring_categories = sorted(
        list(recurring_cat_totals),
        key=lambda c: c["total"],
    )

    # ── 7. Distribution (%) pour le donut ─────────────────────────────────────
    #
    # Le donut est synchronisé avec le KPI actif (active_tab) :
    #   - "sorties"     → répartition des catégories de dépenses
    #   - "entrees"     → répartition des catégories de revenus
    #   - "recurrentes" → répartition des dépenses récurrentes
    #
    # SVG donut math :
    #   Le cercle SVG a r=15.9 → circonférence ≈ 100 (pratique : 1 unité = 1%).
    #   Chaque segment = un <circle> avec :
    #     stroke-dasharray : "pct (100-pct)"  → trace pct% du cercle, masque le reste
    #     stroke-dashoffset : -offset_cumulé  → décale le début du segment
    #   On accumule l'offset au fil des catégories.
    #
    # On définit une fonction locale pour ne pas répéter 3× le même bloc de calcul.

    def _add_donut_math(categories, total_abs):
        """Ajoute pct, dash_array, dash_offset sur chaque catégorie (mutation en place)."""
        cumulative = 0
        for cat in categories:
            cat["pct"] = (
                round(abs(cat["total"]) / total_abs * 100, 1) if total_abs > 0 else 0
            )
            cat["dash_array"] = f"{cat['pct']} {100 - cat['pct']}"
            cat["dash_offset"] = round(-cumulative, 1)
            cumulative += cat["pct"]

    total_expenses_abs = abs(total_expenses)
    total_recurring_abs = abs(total_recurring)

    _add_donut_math(expense_categories, total_expenses_abs)
    _add_donut_math(income_categories, total_income)  # total_income est déjà positif
    _add_donut_math(recurring_categories, total_recurring_abs)

    # Sélection du jeu de données donut selon l'onglet actif.
    # donut_label  : texte affiché au centre du donut
    # donut_total  : montant affiché au centre (toujours positif)
    # donut_sign   : signe affiché devant le montant ("+" ou "−")
    DONUT_CONFIG = {
        "sorties": (expense_categories, total_expenses_abs, "Sorties", "−"),
        "entrees": (income_categories, total_income, "Entrées", "+"),
        "recurrentes": (recurring_categories, total_recurring_abs, "Récurrentes", "−"),
    }
    donut_categories, donut_total, donut_label, donut_sign = DONUT_CONFIG.get(
        active_tab,
        DONUT_CONFIG["sorties"],  # fallback si valeur invalide en session
    )

    # Disponible = ce qu'il reste après toutes les sorties (utilisé en section 8 et 11)
    total_available = total_income + total_expenses  # total_expenses est négatif

    # ── 8. Données JSON pour ECharts (Sankey + Donut) ────────────────────────
    #
    # On sérialise les données en JSON ici (Python) plutôt que dans le template
    # pour garder toute la logique côté serveur. Le template ne fait que passer
    # la chaîne JSON à ECharts via un attribut data-* ou un bloc <script>.
    #
    # --- Sankey ---
    # Structure : income categories (gauche) → expense categories (droite) + Disponible.
    # Chaque catégorie de revenu est reliée à chaque catégorie de dépense
    # proportionnellement à la part de la dépense dans le total sorties.
    # Exemple : si Revenus = 3000 CHF et Alimentation = 20% des sorties,
    #           le lien Revenus → Alimentation a une valeur de 3000 × 0.20 = 600.
    # Cela crée visuellement des "rivières" qui fusionnent au centre, style Finary.

    # Structure Sankey style Finary : 3 colonnes avec nœud pool INVISIBLE au centre.
    #
    # Pourquoi invisible ? ECharts Sankey supporte la propriété `depth` sur chaque
    # nœud — elle force sa colonne horizontale. On place :
    #   depth=0 → income (gauche)
    #   depth=1 → pool invisible (centre) — reçoit tous les revenus, redistribue
    #   depth=2 → expense + disponible (droite)
    #
    # Le nœud pool est coloré comme le fond de la carte (#1e1e2a = surface-3)
    # pour se fondre dans le background. Seuls les flux (streams) sont visibles.
    # Résultat visuel : les revenus "convergent" au centre puis "s'écoulent" vers
    # les dépenses — exactement l'effet Finary.

    POOL = "__pool__"

    sankey_nodes = []
    sankey_links = []

    for cat in income_categories:
        sankey_nodes.append(
            {
                "name": cat["category__name"],
                "slug": cat["category__slug"],
                "itemStyle": {"color": cat["category__colour_hex"] or "#4ade80"},
            }
        )

    sankey_nodes.append(
        {
            "name": POOL,
            "itemStyle": {"color": "#f2c086", "borderWidth": 0},
            "label": {"show": False},
        }
    )

    for cat in expense_categories:
        sankey_nodes.append(
            {
                "name": cat["category__name"],
                "slug": cat["category__slug"],
                "itemStyle": {"color": cat["category__colour_hex"] or "#2d3033"},
            }
        )

    # Gradient d'opacité par lien — même couleur catégorie du début à la fin,
    # mais avec une variation d'opacité : sombre aux bords, lumineux au centre.
    # income → pool (gauche → centre) : opacité 0.15 → 0.55
    # pool   → expense (centre → droite) : opacité 0.55 → 0.15

    # Liens income → pool (seulement si revenus)
    for inc in income_categories:
        color = inc["category__colour_hex"] or "#4ade80"
        sankey_links.append(
            {
                "source": inc["category__name"],
                "target": POOL,
                "value": round(float(inc["total"]), 2),
                "lineStyle": {"color": _gradient(color, 0.15, 0.55)},
            }
        )

    # Liens pool → expense (seulement si dépenses)
    # Séparé du bloc income pour que le Sankey rende les dépenses même sans revenu.
    # Le JS (sankey.js) détecte l'absence de liens income→pool et injecte un
    # nœud fantôme invisible pour alimenter le pool et afficher un message.
    for exp in expense_categories:
        color = exp["category__colour_hex"] or "#888888"
        sankey_links.append(
            {
                "source": POOL,
                "target": exp["category__name"],
                "value": round(float(abs(exp["total"])), 2),
                "lineStyle": {"color": _gradient(color, 0.55, 0.15)},
            }
        )

    # Nœud __disponible__ — invisible, en bas, pour équilibrer le pool.
    # Uniquement quand income ET expenses existent : sans revenu, le pool est
    # alimenté par le fantôme JS et l'équilibre est déjà assuré.
    if income_categories and expense_categories and total_available > 0:
        sankey_nodes.append(
            {
                "name": "__disponible__",
                "itemStyle": {"color": "rgba(0,0,0,0)", "borderWidth": 0},
                "label": {"show": False},
            }
        )
        sankey_links.append(
            {
                "source": POOL,
                "target": "__disponible__",
                "value": round(float(total_available), 2),
                "lineStyle": {"color": "rgba(0,0,0,0)", "opacity": 0},
            }
        )

    # On passe des dicts Python (pas des strings JSON) au contexte.
    # json_script dans le template se charge de la sérialisation JSON → une seule fois.
    # Si on faisait json.dumps() ici ET json_script dans le template, on aurait
    # un double-encodage : le JS recevrait une string au lieu d'un objet.
    sankey_data = {"nodes": sankey_nodes, "links": sankey_links}

    # --- Donut ECharts ---
    donut_data = {
        "segments": [
            {
                "name": cat["category__name"],
                "slug": cat["category__slug"],
                "value": round(float(abs(cat["total"])), 2),
                "itemStyle": {"color": cat["category__colour_hex"] or "#2d3033"},
            }
            for cat in donut_categories
        ],
        "label": donut_label,
        "sign": donut_sign,
        "total": round(float(donut_total), 2),
    }

    # ── 9. Période affichée dans la nav ───────────────────────────────────────
    # Format : "1er avril 2026 — 30 avril 2026"
    # On formate en Python (pas en template) pour garder le mois en français.
    # Seul le 1er du mois a un ordinal en français (1er vs 2, 3, 4...).
    day_start = "1er" if period_start.day == 1 else str(period_start.day)
    day_end = "1er" if period_end.day == 1 else str(period_end.day)
    period_display = (
        f"{day_start} {MOIS_FR[period_start.month].lower()} {period_start.year}"
        f" — "
        f"{day_end} {MOIS_FR[period_end.month].lower()} {period_end.year}"
    )

    # ── 9. Navigation — peut-on aller à droite ? ──────────────────────────────
    #
    # La flèche droite est masquée si period_end atteint ou dépasse le dernier
    # jour du mois courant. On ne peut pas afficher "le futur".
    # `today` est défini en § 1 — pas besoin de le recalculer.
    current_month_end = today.replace(
        day=calendar.monthrange(today.year, today.month)[1]
    )
    can_go_next = period_end < current_month_end

    # ── 10. Catégories actives selon l'onglet ────────────────────────────────
    #
    # active_tab (session) détermine quelle liste on passe au template.
    # Le template n'a qu'une seule variable `active_categories` à afficher —
    # pas besoin de if/elif dans le template, toute la logique reste en Python.
    #
    # Libellés du compteur : "3 catégorie(s) de sorties" / "d'entrées" / "récurrentes"
    TAB_CONFIG = {
        "sorties": (expense_categories, "de sorties"),
        "entrees": (income_categories, "d'entrées"),
        "recurrentes": (recurring_categories, "récurrentes"),
    }
    active_categories, tab_label_suffix = TAB_CONFIG.get(
        active_tab,
        TAB_CONFIG["sorties"],  # fallback sorties si valeur invalide
    )

    # ── 11. Progression budget — arc SVG ────────────────────────────────────
    #
    # Pour chaque catégorie de toutes les listes, on calcule target_pct :
    #   target_pct = abs(total dépensé) / (objectif_mensuel × nb_mois_période) × 100
    #   cappé à 100 — le template affiche en rouge si >= 100 (dépassement).
    #
    # On mutualise la requête BudgetTarget en un seul dict {category_id → amount}
    # pour éviter N requêtes dans la boucle (pattern "prefetch manuel").
    #
    # Pourquoi muter les listes income/expense/recurring et pas juste active_categories ?
    # → active_categories est une référence vers l'une d'elles (pas une copie).
    #   On enrichit toutes les listes car le donut les utilise aussi, et pour ne pas
    #   dépendre de l'ordre d'exécution.
    _targets_map = {t.category_id: t.amount for t in BudgetTarget.objects.all()}
    _period_months = PERIOD_MODE_MONTHS[period_mode]

    for _cat_list in (expense_categories, income_categories, recurring_categories):
        for _cat in _cat_list:
            _monthly = _targets_map.get(_cat["category__id"])
            if _monthly and _monthly > 0:
                _scaled = float(_monthly) * _period_months
                _spent = float(abs(_cat["total"] or 0))
                _raw_pct = _spent / _scaled * 100
                # target_pct : 0-100, pour l'arc SVG (cappé à 100)
                _cat["target_pct"] = min(round(_raw_pct), 100)
                # target_raw_pct : non cappé, pour le texte "XX% de l'objectif"
                _cat["target_raw_pct"] = round(_raw_pct)
                # target_overspend_chf : montant CHF dépassé (None si sous l'objectif)
                _cat["target_overspend_chf"] = (
                    round(_spent - _scaled) if _raw_pct > 100 else None
                )
            else:
                _cat["target_pct"] = None
                _cat["target_raw_pct"] = None
                _cat["target_overspend_chf"] = None

    # ── 12. Contexte → template ───────────────────────────────────────────────
    # total_available calculé en section 8 (avant le Sankey JSON)

    context = {
        # Période
        "period_start": period_start,
        "period_end": period_end,
        "period_label": period_label,
        "period_display": period_display,
        "period_mode": period_mode,
        "can_go_next": can_go_next,
        # Onglet actif
        "active_tab": active_tab,
        # KPIs (Decimal → template les formate avec |floatformat)
        "total_income": total_income,
        "total_expenses": total_expenses,
        "total_expenses_abs": total_expenses_abs,
        "total_recurring": abs(total_recurring),
        "total_available": total_available,
        # Catégories — active_categories = la liste à afficher selon l'onglet
        "active_categories": active_categories,
        "tab_label_suffix": tab_label_suffix,
        # Donut — synchronisé avec l'onglet actif (sorties / entrées / récurrentes)
        "donut_categories": donut_categories,
        "donut_total": donut_total,
        "donut_label": donut_label,
        "donut_sign": donut_sign,
        # Dicts Python pour ECharts — json_script dans le template fait la sérialisation
        "sankey_data": sankey_data,
        "donut_data": donut_data,
        # Toujours passer expense_categories pour les calculs de % déjà présents ailleurs
        "expense_categories": expense_categories,
        # Filtres actifs (multi-select) — pour les dropdowns dans le template
        "accounts": accounts,
        "filter_account_ids": filter_account_ids,
        "all_categories": all_categories,
        "hidden_cat_slugs": hidden_cat_slugs,
        # Préférence affichage décimales (toggle Paramètres)
        # False (défaut) → entiers (32 232 CHF) | True → décimales (32 232,50 CHF)
        "show_decimals": request.session.get("show_decimals", False),
    }

    # HX-Target = "budget-left-section" → swap partiel depuis toggle_filter_*
    # _open_filter indique quel dropdown garder ouvert :
    #   "categories" → cat_filter_open (défaut)
    #   "accounts"   → acc_filter_open
    if request.headers.get("HX-Target") == "budget-left-section":
        _open = getattr(request, "_open_filter", "categories")
        context["cat_filter_open"] = _open == "categories"
        context["acc_filter_open"] = _open == "accounts"
        context["is_htmx_partial"] = True
        return render(request, "budget/partials/_budget_left_section.html", context)

    return render(request, "budget/index.html", context)


# =============================================================================
# budget_set_period — Navigation temporelle (GET → redirect /budget/)
# =============================================================================


@login_required
def budget_set_period(request, action):
    """
    Met à jour la période active en session et redirige vers /budget/.

    URL : /budget/period/<action>/
    Actions valides : "prev" | "next" | "1m" | "3m" | "1y"

    Pattern PRG (Post-Redirect-Get) en version GET :
        Le navigateur fait GET /budget/period/prev/ → on modifie la session
        → on redirect 302 vers GET /budget/ → budget_index se re-render.

    Pourquoi GET et pas POST ?
        Ces boutons ne modifient pas de données en DB — ils changent seulement
        l'état UI (période en session). GET est donc sémantiquement correct.
        Un POST serait excessif pour de la navigation pure.

    Pourquoi redirect et pas render direct ?
        Pour éviter que F5 (rafraîchir) déclenche une double navigation.
        Avec redirect, F5 recharge simplement /budget/.
    """
    today = date.today()

    # Lire l'état courant depuis la session (avec valeurs par défaut)
    current_mode = request.session.get("budget_period_mode", "1m")
    start_str = request.session.get("budget_period_start")
    current_start = date.fromisoformat(start_str) if start_str else today.replace(day=1)

    # ── Changement de mode (1m / 3m / 1y) ───────────────────────────────────
    # On ancre toujours sur le mois courant comme FIN de période.
    # Raison UX : quand on change de mode, on veut voir les données les plus
    # récentes possibles, pas rester bloqué sur un vieux mois de départ.
    # Exemple : si on est en Mai 2025 (1M) et qu'on passe à 3M,
    #   ancien comportement → Mai-Juil 2025 (garde le début)
    #   nouveau comportement → Fév-Avr 2026 (ancre sur aujourd'hui comme fin)
    if action in PERIOD_MODE_MONTHS:
        new_mode = action
        n = PERIOD_MODE_MONTHS[new_mode]

        new_start = _add_months(today.replace(day=1), -(n - 1))
        new_end = _period_end_from_start(new_start, new_mode)

    # ── Navigation prev / next ────────────────────────────────────────────────
    # On décale period_start de ±1 mois, puis on recalcule period_end selon le mode.
    elif action == "prev":
        new_mode = current_mode
        new_start = _add_months(current_start, -1)
        new_end = _period_end_from_start(new_start, new_mode)

    elif action == "next":
        # Bloquer si on est déjà au mois courant (bouton ne devrait pas apparaître)
        current_month_end = today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        )
        current_end = _period_end_from_start(current_start, current_mode)
        if current_end >= current_month_end:
            return redirect("budget:index")  # no-op silencieux

        new_mode = current_mode
        new_start = _add_months(current_start, 1)
        new_end = _period_end_from_start(new_start, new_mode)

    else:
        # Action inconnue → no-op
        return redirect("budget:index")

    # ── Persister en session ──────────────────────────────────────────────────
    request.session["budget_period_mode"] = new_mode
    request.session["budget_period_start"] = new_start.isoformat()
    request.session["budget_period_end"] = new_end.isoformat()

    # Redirect vers la page appelante (Referer) — permet d'utiliser set_period
    # depuis n'importe quelle page (index, category_detail…) sans URL dédiée.
    # Fallback sur budget:index si pas de Referer (direct URL, test, etc.).
    return redirect(safe_referer(request))


# =============================================================================
# budget_set_tab — Bascule l'onglet actif (GET → redirect /budget/)
# =============================================================================


@login_required
def budget_set_tab(request, tab):
    """
    Met à jour l'onglet actif en session et redirige vers /budget/.

    URL : /budget/tab/<tab>/
    tab valides : "sorties" | "entrees" | "recurrentes"

    Même pattern que budget_set_period : GET → session update → redirect.
    Aucune écriture en DB — seulement l'état UI en session.
    """
    VALID_TABS = {"sorties", "entrees", "recurrentes"}

    if tab in VALID_TABS:
        request.session["budget_active_tab"] = tab

    return redirect("budget:index")


# =============================================================================
# budget_set_cat_tab — Bascule l'onglet actif de la page catégorie (GET → redirect)
# =============================================================================


@login_required
def budget_set_cat_tab(request, tab):
    """
    Met à jour l'onglet actif de la page catégorie en session et redirige vers
    la page appelante (HTTP_REFERER).

    URL : /budget/categorie/tab/<tab>/
    tab valides : "transactions" | "subcategories" | "objectif"

    Même pattern que budget_set_tab mais pour la page catégorie :
    - Pas de redirect fixe vers /budget/ — on revient sur la page catégorie
      courante via HTTP_REFERER.
    - L'onglet actif (cat_tab) est lu dans budget_category_detail pour
      décider quelle valeur mettre en avant dans les KPIs.
    """
    VALID_TABS = {"transactions", "subcategories", "objectif"}

    if tab in VALID_TABS:
        request.session["budget_cat_tab"] = tab

    return redirect(safe_referer(request))


# =============================================================================
# budget_set_period_month — Saute vers un mois précis (GET → redirect)
# =============================================================================


@login_required
def budget_set_period_month(request, year, month):
    """
    Saute vers un mois spécifique en écrivant directement period_start/end en session.
    Utilisé par le bar chart historique de category_detail quand on clique une barre.

    URL : /budget/period/month/<year>/<month>/
    Même pattern PRG que budget_set_period : GET → session → redirect referer.

    Pourquoi une vue dédiée plutôt que budget_set_period ?
        budget_set_period prend une action ("prev", "next", "1m"...) et calcule
        la période relative à aujourd'hui. Ici on veut un mois absolu arbitraire —
        on écrit donc directement les clés session budget_period_start/end.
    """
    try:
        target_date = date(int(year), int(month), 1)
    except ValueError:
        return redirect(safe_referer(request))

    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    request.session["budget_period_mode"] = "1m"
    request.session["budget_period_start"] = target_date.isoformat()
    request.session["budget_period_end"] = target_date.replace(day=last_day).isoformat()

    return redirect(safe_referer(request))


# =============================================================================
# budget_toggle_filter_account — Toggle multi-select filtre compte (GET)
# =============================================================================


@login_required
def budget_toggle_filter_account(request, account_ref):
    """
    Toggle un compte dans le filtre blacklist stocké en session.

    URL : /budget/filter/account/<account_ref>/
    account_ref="all"/"0" → réinitialise (aucun masqué = tout visible)
    account_ref="none"    → masque tous les comptes
    account_ref="<int>"   → toggle le compte spécifique

    Blacklist : budget_filter_accounts_hidden = IDs des comptes EXCLUS.
    Vide = tout visible (cercles dorés par défaut). Non-vide = ces comptes masqués.
    """
    hidden = request.session.get("budget_filter_accounts_hidden", [])

    if account_ref in ("all", "0", 0):
        # Tout sélectionner → aucune exclusion
        hidden = []
    elif account_ref == "none":
        # Tout masquer → exclure tous les comptes actifs de l'utilisateur
        hidden = list(
            Account.objects.for_user(request.user)
            .filter(is_active=True)
            .values_list("id", flat=True)
        )
    else:
        try:
            account_id = int(account_ref)
        except (ValueError, TypeError):
            # Référence non numérique (URL forgée) → toggle ignoré, mais tracé.
            logger.debug(
                "toggle_filter_account rejected ref=%r reason=not_an_id", account_ref
            )
            account_id = None
        if account_id is not None:
            if account_id in hidden:
                hidden = [i for i in hidden if i != account_id]
            else:
                hidden = hidden + [account_id]

    request.session["budget_filter_accounts_hidden"] = hidden
    logger.debug(
        "toggle_filter_account user=%s ref=%s hidden=%s",
        request.user.id,
        account_ref,
        hidden,
    )
    if request.headers.get("HX-Request"):
        if request.headers.get("HX-Target") == "budget-left-section":
            request._open_filter = "accounts"
            return budget_index(request)
        request._panel_acc_filter_open = True
        return budget_panel_transactions(request)
    return redirect(safe_referer(request))


# =============================================================================
# budget_toggle_filter_category — Toggle multi-select filtre catégorie (GET)
# =============================================================================


@login_required
def budget_toggle_filter_category(request, slug):
    """
    Toggle une catégorie dans le filtre blacklist stocké en session.

    URL : /budget/filter/category/<slug>/
    slug="all"  → réinitialise (tout visible — vide la liste hidden)
    slug="none" → masque toutes les catégories actives
    Autre slug  → toggle : visible ↔ masqué

    Blacklist : budget_filter_categories_hidden = slugs des catégories EXCLUES.
    Vide = tout visible. Non-vide = ces catégories sont masquées du budget.

    HTMX : si HX-Request → retourne le fragment panel_transactions (même que toggle_account).
    Non-HTMX : redirect vers budget_index.
    """
    hidden = request.session.get("budget_filter_categories_hidden", [])

    if slug == "all":
        # Tout sélectionner → aucune exclusion
        hidden = []
    elif slug == "none":
        # Tout masquer → exclure toutes les catégories actives visibles par l'user
        # (#137 : ne pas faire fuiter les slugs perso d'un autre user dans la session).
        hidden = list(
            Category.objects.for_user(request.user)
            .filter(is_active=True)
            .values_list("slug", flat=True)
        )
    elif slug in hidden:
        # Ré-afficher → retirer de la liste d'exclusion
        hidden = [s for s in hidden if s != slug]
    else:
        # Masquer → ajouter à la liste d'exclusion
        hidden = hidden + [slug]

    request.session["budget_filter_categories_hidden"] = hidden
    logger.debug(
        "toggle_filter_category user=%s slug=%s hidden=%s",
        request.user.id,
        slug,
        hidden,
    )

    if request.headers.get("HX-Request"):
        # HX-Target indique le contexte d'appel :
        #   "budget-left-section" → swap section gauche index (dropdown reste ouvert)
        #   autre / absent        → fragment panel transactions (Étape 4)
        if request.headers.get("HX-Target") == "budget-left-section":
            request._open_filter = "categories"
            return budget_index(request)
        return budget_panel_transactions(request)
    return redirect("budget:index")


# =============================================================================
# budget_toggle_decimals — Bascule l'affichage des décimales dans les KPIs
# =============================================================================


@require_POST
@login_required
def budget_toggle_decimals(request):
    """
    Bascule la préférence d'affichage des décimales dans les montants CHF.

    URL : /budget/toggle-decimals/  (POST)
    Action : flip request.session['show_decimals'] (bool, default False)
    Réponse : redirect vers /budget/ (full page reload pour mettre à jour les KPIs)

    Pourquoi un full reload et pas HTMX partiel ?
        Les montants sont dispersés dans plusieurs zones du template (KPIs, liste
        catégories, donut label). Un reload complet est plus simple et fiable
        qu'un swap HTMX multi-cible. La page budget se charge en <200ms donc pas
        d'impact UX perceptible.

    Pourquoi stocker en session et pas en cookie côté client ?
        Cohérence avec tous les autres états UI (filtres, onglet, période).
        La session Django est serveur : pas de JS complexe côté client.
    """
    current = request.session.get("show_decimals", False)
    request.session["show_decimals"] = not current
    logger.debug(
        "toggle_decimals: user=%s show_decimals %s → %s",
        request.user.username,
        current,
        not current,
    )
    return redirect("budget:index")

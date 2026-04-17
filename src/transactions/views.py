"""
transactions/views.py — Vues de l'application Budget

Pattern de toutes les vues ici :
    1. Lire l'état depuis request.session (période active, onglet actif)
    2. Construire le queryset de base (filtres fixes : non ignoré, non virement)
    3. Appliquer les filtres de période
    4. Calculer les agrégats (KPIs + totaux par catégorie)
    5. Retourner le contexte au template

Pourquoi tout en session Django ?
    → Décision d'archi 2026-04-01 : pas d'URL params pour l'état UI.
    Chaque requête POST/HTMX met à jour la session, puis redirige (ou re-render)
    en GET pour que le navigateur voie toujours une URL propre.
"""

import calendar
import json
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.views.decorators.http import require_POST

from transactions.models import CategorizationRule, Category, SubCategory, Transaction

# =============================================================================
# Helpers — arithmétique sur les dates
# =============================================================================

# Nombre de mois dans chaque mode de période.
# Utilisé pour calculer period_end à partir de period_start.
PERIOD_MODE_MONTHS = {"1m": 1, "3m": 3, "1y": 12}

MOIS_FR = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}


def _add_months(d, n):
    """
    Ajoute n mois à la date d (n peut être négatif).

    Exemple : _add_months(date(2026, 1, 31), 1) → date(2026, 2, 28)
    Le jour est réduit au dernier jour du mois si nécessaire (ex: 31 jan → 28 fév).

    Pourquoi ne pas utiliser timedelta(days=30) ?
    → Les mois n'ont pas le même nombre de jours. +30j depuis le 1er mars donne
      le 31 mars, pas le 1er avril. _add_months(date(2026, 3, 1), 1) → 2026-04-01. ✓
    """
    month = d.month - 1 + n  # mois 0-indexé (0 = janvier)
    year = d.year + month // 12  # débordement d'année si month < 0 ou > 11
    month = month % 12 + 1  # retour en 1-indexé (1-12)
    day = min(d.day, calendar.monthrange(year, month)[1])  # clamp au dernier jour
    return d.replace(year=year, month=month, day=day)


def _period_end_from_start(start, mode):
    """
    Calcule le dernier jour de la période à partir du premier jour et du mode.

    Exemples :
        _period_end_from_start(date(2026, 4, 1), "1m") → date(2026, 4, 30)
        _period_end_from_start(date(2026, 2, 1), "3m") → date(2026, 4, 30)
        _period_end_from_start(date(2026, 4, 1), "1y") → date(2027, 3, 31)

    On calcule le mois de fin = start + (n_mois - 1), puis on prend le dernier jour.
    Ex pour 3m depuis avril : fin = juin = dernier jour de juin = 30 juin.
    """
    n = PERIOD_MODE_MONTHS[mode]
    end_month_start = _add_months(start, n - 1)  # premier jour du dernier mois
    last_day = calendar.monthrange(end_month_start.year, end_month_start.month)[1]
    return end_month_start.replace(day=last_day)


# =============================================================================
# _resolve_bank_icon_map — Helper privé : dict { icon_slug → URL statique }
# =============================================================================


def _resolve_bank_icon_map():
    """
    Construit un dict { icon_slug → URL statique de l'icône banque }.

    Scanne le dossier static/icons/banks/miniature/ et applique une priorité
    d'extension pour gérer les doublons :
        svg > png > jpg > jpeg  (SVG = meilleure qualité)

    Retourne {} si le dossier n'existe pas (ex: tests sans static).

    Pourquoi une fonction séparée et pas inline dans chaque vue ?
        Cette logique était dupliquée dans budget_panel_transactions() et
        serait dupliquée à nouveau dans budget_toggle_ignore().
        En Python : si tu copies/colles du code, c'est le signal qu'il faut
        une fonction. Ici c'est un helper privé (préfixe _) → usage interne.

    Pourquoi pas un cache module-level ?
        Les icônes peuvent changer (make update-bank-logos). En dev, on veut
        voir les changements sans redémarrer Django. En prod, le volume est
        faible (< 10 banques) — le scan est négligeable.
    """
    EXTENSION_PRIORITY = {"svg": 0, "png": 1, "jpg": 2, "jpeg": 3}
    icon_dir = Path(settings.BASE_DIR) / "static" / "icons" / "banks" / "miniature"

    if not icon_dir.exists():
        return {}

    # { slug → (priority, filename) } — on garde la meilleure extension par slug
    _best = {}
    for f in icon_dir.iterdir():
        if not f.is_file() or f.name.startswith("."):
            continue
        ext = f.suffix.lstrip(".").lower()
        priority = EXTENSION_PRIORITY.get(ext, 99)
        if f.stem not in _best or priority < _best[f.stem][0]:
            _best[f.stem] = (priority, f.name)

    return {
        slug: static(f"icons/banks/miniature/{fname}")
        for slug, (_, fname) in _best.items()
    }


# =============================================================================
# transaction_list — Page Budget principale
# =============================================================================


@login_required
def transaction_list(request):
    """
    Page Budget : agrégation des transactions par catégorie pour la période active.

    URL : /budget/
    Template : transactions/budget.html

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

    period_start_str = request.session.get("budget_period_start")
    period_end_str = request.session.get("budget_period_end")

    if period_start_str and period_end_str:
        # Reconstituer les objets date depuis les strings stockés en session
        period_start = date.fromisoformat(period_start_str)
        period_end = date.fromisoformat(period_end_str)
    else:
        # Initialiser au mois en cours
        period_start = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        period_end = today.replace(day=last_day)

        # Persister en session
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
    qs = Transaction.objects.filter(
        date__gte=period_start,
        date__lte=period_end,
        is_ignored=False,
        is_internal_transfer=False,
    )

    # ── 4. KPIs ───────────────────────────────────────────────────────────────
    #
    # Django .aggregate() exécute UNE requête SQL et retourne un dict.
    # Ex: {"total": Decimal('-2341.50')} ou {"total": None} si aucune transaction.
    #
    # Entrées = montants positifs (salaire, remboursements, cadeaux...)
    # Sorties = montants négatifs (dépenses) — on garde le signe, on l'affiche abs()
    # Récurrentes = dépenses marquées is_recurring=True (loyer, abo...)

    total_income = qs.filter(amount__gt=0).aggregate(total=Sum("amount"))["total"] or 0

    total_expenses = (
        qs.filter(amount__lt=0).aggregate(total=Sum("amount"))["total"] or 0
    )

    total_recurring = (
        qs.filter(amount__lt=0, is_recurring=True).aggregate(total=Sum("amount"))[
            "total"
        ]
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
        .annotate(total=Sum("amount"))
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
        .annotate(total=Sum("amount"))
        .order_by("category__order")
    )
    recurring_categories = sorted(
        list(recurring_cat_totals),
        key=lambda c: c["total"],
    )

    # ── 7. Distribution (%) pour le donut ─────────────────────────────────────
    #
    # On calcule la part de chaque catégorie de dépenses sur le total des sorties.
    # abs() car total_expenses est négatif.
    total_expenses_abs = abs(total_expenses)

    # SVG donut math :
    #   Le cercle SVG a r=15.9 → circonférence ≈ 100 (pratique : 1 unité = 1%).
    #   Chaque segment = un <circle> avec :
    #     stroke-dasharray : "pct (100-pct)"  → trace pct% du cercle, masque le reste
    #     stroke-dashoffset : -offset_cumulé  → décale le début du segment
    #   On accumule l'offset au fil des catégories.
    cumulative_pct = 0
    for cat in expense_categories:
        if total_expenses_abs > 0:
            cat["pct"] = round(abs(cat["total"]) / total_expenses_abs * 100, 1)
        else:
            cat["pct"] = 0
        # Valeurs précalculées pour éviter la logique dans le template
        cat["dash_array"] = f"{cat['pct']} {100 - cat['pct']}"
        cat["dash_offset"] = round(-cumulative_pct, 1)
        cumulative_pct += cat["pct"]

    # ── 8. Période affichée dans la nav ───────────────────────────────────────
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

    # ── 11. Contexte → template ───────────────────────────────────────────────
    # Disponible = ce qu'il reste après toutes les sorties
    total_available = total_income + total_expenses  # expenses est négatif → addition

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
        # Toujours passer expense_categories au donut (la distribution reste en sorties)
        "expense_categories": expense_categories,
    }

    return render(request, "transactions/budget.html", context)


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
        → on redirect 302 vers GET /budget/ → transaction_list se re-render.

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
    # On bascule vers le nouveau mode en gardant la même période de départ si possible.
    # Si la nouvelle période dépasse le mois courant, on revient au mois courant.
    if action in PERIOD_MODE_MONTHS:
        new_mode = action
        new_start = current_start  # on tente de garder le même mois de départ

        # Calculer la fin avec le nouveau mode
        new_end = _period_end_from_start(new_start, new_mode)

        # Si la fin déborde dans le futur, recentrer sur le mois courant (comme fin)
        current_month_end = today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        )
        if new_end > current_month_end:
            # Décaler le début pour que la fin = dernier mois courant
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
            return redirect("transactions:list")  # no-op silencieux

        new_mode = current_mode
        new_start = _add_months(current_start, 1)
        new_end = _period_end_from_start(new_start, new_mode)

    else:
        # Action inconnue → no-op
        return redirect("transactions:list")

    # ── Persister en session ──────────────────────────────────────────────────
    request.session["budget_period_mode"] = new_mode
    request.session["budget_period_start"] = new_start.isoformat()
    request.session["budget_period_end"] = new_end.isoformat()

    return redirect("transactions:list")


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

    return redirect("transactions:list")


# =============================================================================
# budget_panel_transactions — Partial HTMX : liste transactions (right panel)
# =============================================================================


@login_required
def budget_panel_transactions(request):
    """
    Partial HTMX — chargé dans #panel-content quand on clique "Tout voir".

    URL : /budget/panel/transactions/
    Template : transactions/_panel_tx_list.html  (fragment, pas une page complète)

    Principe :
        Cette vue ne retourne PAS une page HTML complète avec <html>/<head>/<body>.
        Elle retourne uniquement le fragment HTML qui sera injecté dans #panel-content
        par HTMX (hx-swap="innerHTML").

    Pourquoi lire la période depuis la session plutôt que la recalculer ?
        - La session contient déjà la période choisie par l'utilisateur.
        - Recalculer ici risquerait de désynchroniser (ex: si l'user a navigué en 3M).
        - Même source de vérité que transaction_list().

    Limite à 200 transactions :
        - Au-delà, le right panel devient inutilisable (scroll infini).
        - La pagination sera ajoutée Phase 2A si besoin.
    """
    today = date.today()

    # ── Lire la période depuis la session (même logique que transaction_list) ──
    period_start_str = request.session.get("budget_period_start")
    period_end_str = request.session.get("budget_period_end")

    if period_start_str and period_end_str:
        period_start = date.fromisoformat(period_start_str)
        period_end = date.fromisoformat(period_end_str)
    else:
        # Fallback : mois en cours si session vide
        period_start = today.replace(day=1)
        period_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    # ── Icônes banque ─────────────────────────────────────────────────────────
    # Délégué au helper privé _resolve_bank_icon_map() — voir définition plus haut.
    bank_icon_map = _resolve_bank_icon_map()

    # ── Recherche texte libre (filtre live) ──────────────────────────────────
    #
    # "q" est envoyé par le composant search_bar.html via hx-get avec name="q".
    # On cherche dans merchant_name ET description_raw (OR).
    # icontains = insensible à la casse.
    q = request.GET.get("q", "").strip()

    # ── Queryset transactions ─────────────────────────────────────────────────
    #
    # list() force l'évaluation du queryset pour pouvoir annoter les objets.
    # select_related → 1 JOIN au lieu de N+1 requêtes en template.
    # order_by("-date", "-id") → plus récentes en premier, "-id" = tie-breaker.
    # ── Queryset transactions ─────────────────────────────────────────────────
    #
    # Pas de filtre is_ignored=False ici — contrairement à transaction_list()
    # qui exclut les ignorées des KPIs budget, le panel les affiche en grisé.
    # L'utilisateur doit voir ce qu'il a ignoré pour pouvoir le réactiver.
    qs = Transaction.objects.filter(
        date__gte=period_start,
        date__lte=period_end,
        is_internal_transfer=False,
    )
    if q:
        qs = qs.filter(Q(merchant_name__icontains=q) | Q(description_raw__icontains=q))
    tx_list = list(
        qs.select_related(
            "category", "subcategory", "account", "account__bank"
        ).order_by("-date", "-id")[:200]
    )

    # Annoter chaque transaction avec l'URL résolue de l'icône banque.
    # tx.bank_icon_url est ensuite accessible directement dans le template.
    for tx in tx_list:
        slug = tx.account.bank.icon_slug if tx.account and tx.account.bank else ""
        tx.bank_icon_url = bank_icon_map.get(slug, "")

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
        "transactions/_panel_tx_list.html",
        {
            "transactions": tx_list,
            "period_start": period_start,
            "period_end": period_end,
            "period_mode": period_mode,
            "period_label": period_label,
            "can_go_next": can_go_next,
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
        → "list"   : retourne _panel_tx_row.html  (swap outerHTML sur #tx-id)
        → "detail" : retourne _panel_tx_detail.html (swap innerHTML sur #panel-content)

    Pourquoi deux templates de retour ?
        La vue est appelée depuis deux endroits :
        1. La liste transactions (_panel_tx_row.html) — le bouton œil en hover
        2. Le panneau détail (_panel_tx_detail.html) — le toggle "Inclure dans l'analyse"
        Le champ source=detail dans le formulaire HTMX indique quel fragment retourner.
    """
    tx = get_object_or_404(
        Transaction.objects.select_related(
            "category", "subcategory", "account", "account__bank"
        ),
        pk=tx_id,
    )

    tx.is_ignored = not tx.is_ignored
    tx.save(update_fields=["is_ignored"])

    bank_icon_map = _resolve_bank_icon_map()
    slug = tx.account.bank.icon_slug if tx.account and tx.account.bank else ""
    bank_icon_url = bank_icon_map.get(slug, "")

    # source=detail → appelé depuis le panneau détail → retourner le panneau entier
    if request.POST.get("source") == "detail":
        return render(
            request,
            "transactions/_panel_tx_detail.html",
            {"tx": tx, "bank_icon_url": bank_icon_url},
        )

    # source=list (défaut) → appelé depuis la liste → retourner juste la ligne
    return render(
        request,
        "transactions/_panel_tx_row.html",
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
    Template : transactions/_panel_category_picker.html

    Déclenché par clic sur une ligne de transaction dans _panel_tx_row.html.

    Pourquoi deux listes séparées (system / custom) ?
        La spec Finary distingue visuellement "Catégories personnalisées" (créées
        par l'utilisateur, is_system=False) et "Catégories" (système, is_system=True).
        En Python c'est plus clair qu'un seul queryset avec groupby en template.
    """
    tx_id = request.GET.get("tx_id")
    tx = get_object_or_404(
        Transaction.objects.select_related("category", "subcategory"),
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

    return render(
        request,
        "transactions/_panel_category_picker.html",
        {
            "tx": tx,
            "system_cats": system_cats,
            "custom_cats": custom_cats,
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
    Template : transactions/_panel_tx_list.html  (via budget_panel_transactions)

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

    tx = get_object_or_404(Transaction, pk=tx_id)
    tx.category = get_object_or_404(Category, pk=cat_id)
    # subcategory est optionnelle — SET_NULL si non fournie
    tx.subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None
    # categorization_source = "manual" : l'utilisateur a choisi lui-même
    # (distinct de "rule" → règle auto, "ai" → Claude API, "default" → import)
    tx.categorization_source = "manual"
    tx.save(update_fields=["category", "subcategory", "categorization_source"])

    # Retourner le fragment liste (état A du panel)
    response = budget_panel_transactions(request)

    # HX-Trigger : déclenche l'événement JS "categoryChanged" après swap HTMX
    # Le JS dans base_app.html écoute cet événement et affiche le toast
    tx_display = tx.merchant_name or tx.description_raw[:30]

    # Extraction du keyword pour pré-remplir le formulaire de règle.
    # On split description_raw sur les séparateurs courants (espace, *, +, -, /)
    # et on garde le premier token de 3+ caractères qui n'est pas un nombre pur.
    # Exemples : "VIR APPLE.COM/BILL 123" → "VIR", "MIGROS LAUSANNE" → "MIGROS"
    raw_tokens = re.split(r"[\s\*\+\-\/]+", tx.description_raw.upper())
    keyword_tokens = [t for t in raw_tokens if len(t) >= 3 and not t.isdigit()]
    keyword = keyword_tokens[0] if keyword_tokens else tx_display

    response["HX-Trigger"] = json.dumps(
        {
            "categoryChanged": {
                "tx_name": tx_display,
                "cat_name": tx.category.name,
                "tx_id": tx.id,
                "keyword": keyword,
            }
        }
    )
    return response


# =============================================================================
# budget_panel_rule_create — Partial HTMX : formulaire création règle (GET)
# =============================================================================


@login_required
def budget_panel_rule_create(request):
    """
    Partial HTMX — panneau "Créer une règle intelligente".

    URL      : GET /budget/panel/rule-create/?tx_id=X&keyword=MIGROS
    Target   : #panel-content
    Template : transactions/_panel_rule_create.html

    Déclenché par le bouton "Créer une règle automatique →" dans le toast,
    après qu'une transaction a été catégorisée manuellement.

    Contexte transmis au template :
        tx       — Transaction source (pour afficher son nom + catégorie actuelle)
        keyword  — Token pré-rempli extrait de description_raw (ex: "MIGROS")
        categories — QuerySet Category actives triées par order (pour le dropdown)
    """
    tx_id = request.GET.get("tx_id")
    keyword = request.GET.get("keyword", "").strip()

    tx = get_object_or_404(
        Transaction.objects.select_related("category", "subcategory"),
        pk=tx_id,
    )

    # Tokens cliquables : on split le meilleur nom disponible.
    # Priorité : merchant_name (déjà nettoyé) > description_raw (texte brut banque).
    # merchant_name = "MIGROS LAUSANNE" → 2 tokens propres
    # description_raw = "VIR SEPA MIGROS LAUSANNE CB 12345" → beaucoup de bruit
    source_text = tx.merchant_name if tx.merchant_name else tx.description_raw
    raw_tokens = re.split(r"[\s\*\+\-\/\.]+", source_text.upper())
    seen = set()
    tokens = []
    for t in raw_tokens:
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            tokens.append(t)

    # Catégories séparées perso / système — même logique que le picker classique
    custom_cats = (
        Category.objects.filter(is_active=True, is_system=False)
        .prefetch_related("subcategories")
        .order_by("order")
    )
    system_cats = (
        Category.objects.filter(is_active=True, is_system=True)
        .prefetch_related("subcategories")
        .order_by("order")
    )

    return render(
        request,
        "transactions/_panel_rule_create.html",
        {
            "tx": tx,
            "keyword": keyword,
            "tokens": tokens,
            "custom_cats": custom_cats,
            "system_cats": system_cats,
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
    Template : transactions/_panel_rule_preview.html

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

    category = get_object_or_404(Category, pk=cat_id)
    subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None

    # Compter les transactions affectées SANS les modifier
    # Même filtre que le bulk apply réel — pour que le count soit exact
    affected_count = (
        Transaction.objects.filter(description_raw__icontains=keyword)
        .exclude(categorization_source="manual")
        .count()
    )

    return render(
        request,
        "transactions/_panel_rule_preview.html",
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
    Template : transactions/_panel_rule_confirm.html

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

    category = get_object_or_404(Category, pk=cat_id)
    subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None

    # Créer la règle — get_or_create évite les doublons si même keyword + catégorie
    # update_fields non applicable ici : on veut l'objet complet pour le contexte
    rule, created = CategorizationRule.objects.get_or_create(
        keyword=keyword,
        category=category,
        defaults={
            "subcategory": subcategory,
            "target_field": "description_raw",  # wizard UI → toujours description_raw
            "priority": 10,
            "is_active": True,
        },
    )

    # Bulk apply : toutes les transactions dont description_raw contient le keyword
    # en excluant les catégorisations manuelles (décision explicite de l'user)
    # icontains = case-insensitive LIKE '%keyword%' en SQL → 1 seule query
    updated_count = (
        Transaction.objects.filter(
            description_raw__icontains=keyword,
        )
        .exclude(
            categorization_source="manual",
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
        "transactions/_panel_rule_confirm.html",
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
# budget_panel_tx_detail — Partial HTMX : détail d'une transaction (GET)
# =============================================================================


@login_required
def budget_panel_tx_detail(request):
    """
    Partial HTMX — panneau "Détails de la transaction" (état C du right panel).

    URL      : GET /budget/panel/tx-detail/?tx_id=X
    Target   : #panel-content  (remplace tout le contenu du right panel)
    Template : transactions/_panel_tx_detail.html

    Déclenché par clic sur une ligne de transaction dans _panel_tx_row.html.
    Remplace l'ancien comportement qui ouvrait directement le picker catégorie.

    Pourquoi select_related avec "account__bank" ?
        On affiche le nom du compte et l'icône banque dans le panneau.
        Sans select_related, Django ferait 2 requêtes supplémentaires
        (tx → account, account → bank) au lieu d'un seul JOIN.
    """
    tx_id = request.GET.get("tx_id")
    tx = get_object_or_404(
        Transaction.objects.select_related(
            "category", "subcategory", "account", "account__bank"
        ),
        pk=tx_id,
    )

    # Résolution icône banque — même helper que les autres vues panel
    bank_icon_map = _resolve_bank_icon_map()
    slug = tx.account.bank.icon_slug if tx.account and tx.account.bank else ""
    bank_icon_url = bank_icon_map.get(slug, "")

    return render(
        request,
        "transactions/_panel_tx_detail.html",
        {
            "tx": tx,
            "bank_icon_url": bank_icon_url,
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
    Template : transactions/_panel_tx_detail.html

    Pointer = vérifier que la transaction correspond au relevé de compte.
    Appelé uniquement depuis le panneau détail — pas de source à détecter.
    """
    tx = get_object_or_404(
        Transaction.objects.select_related(
            "category", "subcategory", "account", "account__bank"
        ),
        pk=tx_id,
    )

    tx.is_reconciled = not tx.is_reconciled
    tx.save(update_fields=["is_reconciled"])

    bank_icon_map = _resolve_bank_icon_map()
    slug = tx.account.bank.icon_slug if tx.account and tx.account.bank else ""
    bank_icon_url = bank_icon_map.get(slug, "")

    # source=list → appelé depuis la ligne liste → retourner juste la ligne
    if request.POST.get("source") != "detail":
        return render(
            request,
            "transactions/_panel_tx_row.html",
            {"tx": tx, "bank_icon_url": bank_icon_url},
        )

    # source=detail → appelé depuis le panneau détail → retourner le panneau entier
    return render(
        request,
        "transactions/_panel_tx_detail.html",
        {"tx": tx, "bank_icon_url": bank_icon_url},
    )

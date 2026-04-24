"""
budget/views.py — Vues de l'application Budget

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

Pourquoi les vues sont ici et pas dans transactions/ ?
    L'app transactions/ contient les modèles et services (données).
    L'app budget/ contient les vues et templates (UI).
    Séparation claire : on importe les modèles depuis transactions.models.
"""

import calendar
import json
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_POST

from transactions.models import (
    BudgetTarget,
    CategorizationRule,
    Category,
    SubCategory,
    Transaction,
)

# =============================================================================
# Helpers — arithmétique sur les dates
# =============================================================================

# Nombre de mois dans chaque mode de période.
# Utilisé pour calculer period_end à partir de period_start.
PERIOD_MODE_MONTHS = {"1m": 1, "3m": 3, "1y": 12}

# Tokens banque sans valeur pour les règles de catégorisation.
# Filtrés lors de la génération des chips — ne doivent pas apparaître comme suggestions.
# Source : métadonnées Yuh (CHF) et CIC (EUR), codes de paiement standard CH/EU.
_RULE_NOISE_TOKENS = {
    # Types de paiement et terminaux
    "PSC",
    "CB",
    "TPE",
    "NFC",
    "SCV",
    "SCC",
    # Verbes / mots d'action banque
    "PAIEMENT",
    "RETRAIT",
    "ACHAT",
    "VIREMENT",
    "VIR",
    "PRELEVEMENT",
    "SEPA",
    "DEBIT",
    "CREDIT",
    "ORDRE",
    "TRANSFERT",
    "REMISE",
    "DEPOT",
    # Instruments de paiement
    "CARTE",
    "CARD",
    "VISA",
    "MASTERCARD",
    "MAESTRO",
    "TWINT",
    "PAYPAL",
    # Devises
    "CHF",
    "EUR",
    "GBP",
    "USD",
    "CAD",
    "JPY",
    # Codes pays / zones
    "CH",
    "FR",
    "DE",
    "BE",
    "LU",
    "UK",
    "EU",
    # Mots génériques bruit
    "SANS",
    "CONTACT",
    "BANCAIRE",
    "BANQUE",
    "TRANSACTION",
    "PRET",
    "NO",
    "NUM",
    "REF",
    "ID",
    "PAY",
    "PAYMENT",
    "NUMERO",
    "CODE",
}


def _keyword_q(keyword: str):
    r"""
    Retourne un Q filtre Django pour description_raw basé sur le keyword.

    Règles :
      - Chaque mot du keyword doit apparaître comme MOT ENTIER dans description_raw.
        Ex : keyword="ESSO" ne match pas "ESSOF108" car \y (word boundary PostgreSQL)
        sépare les tokens alphanumériques.
      - Plusieurs mots → condition AND (toutes les parties doivent être présentes).
      - Keyword vide → retourne Q(pk__in=[]) pour ne matcher aucune transaction.

    Pourquoi iregex et pas icontains ?
        icontains correspond à LIKE '%mot%' — ne respecte pas les frontières de mots.
        iregex utilise le moteur regex PostgreSQL qui supporte \y (word boundary),
        ce qui correspond exactement à un token complet.
    """
    from django.db.models import Q

    words = [w for w in keyword.upper().split() if w]
    if not words:
        # Aucun mot → on ne veut matcher rien (protection anti-apply-all)
        return Q(pk__in=[])
    q = Q()
    for word in words:
        # \y = word boundary dans PostgreSQL. re.escape protège les caractères spéciaux.
        pattern = r"\y" + re.escape(word) + r"\y"
        q &= Q(description_raw__iregex=pattern)
    return q


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

    Scanne le dossier static/icons/banks/svg/ — SVGs sans fond, avec fill="currentColor".
    Le SVG currentColor permet d'adapter la couleur de l'icône via CSS (dark theme natif).

    Retourne {} si le dossier n'existe pas (ex: tests sans static).

    Pourquoi svg/ et pas miniature/ ?
        Les PNG dans miniature/ ont un fond blanc intégré dans le fichier → carré blanc
        moche sur dark theme. Les SVG dans svg/ sont des paths purs sans fond — ils
        prennent la couleur CSS de leur conteneur via currentColor.

    ⚠️  AJOUTER UN NOUVEAU LOGO BANQUE
        → Déposer le SVG dans static/icons/banks/svg/<slug>.svg
        → Le nom du fichier doit correspondre à Bank.icon_slug en base
        → Le SVG doit utiliser fill="currentColor" (pas de fill="#xxx" hardcodé)
        → Si le SVG a un fond blanc/coloré intégré : l'enlever dans Inkscape/Figma avant

    Pourquoi pas un cache module-level ?
        Les icônes peuvent changer (make update-bank-logos). En dev, on veut
        voir les changements sans redémarrer Django. En prod, le volume est
        faible (< 10 banques) — le scan est négligeable.
    """
    base = Path(settings.BASE_DIR) / "static" / "icons" / "banks"
    svg_dir = base / "svg"
    miniature_dir = base / "miniature"

    # Collecte tous les slugs disponibles dans miniature/ (PNG/JPG = fallback)
    result = {}
    if miniature_dir.exists():
        EXTENSION_PRIORITY = {"svg": 0, "png": 1, "jpg": 2, "jpeg": 3}
        _best = {}
        for f in miniature_dir.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            ext = f.suffix.lstrip(".").lower()
            priority = EXTENSION_PRIORITY.get(ext, 99)
            if f.stem not in _best or priority < _best[f.stem][0]:
                _best[f.stem] = (priority, f.name)
        result = {
            slug: static(f"icons/banks/miniature/{fname}")
            for slug, (_, fname) in _best.items()
        }

    # Écrase avec les SVG quand disponibles (priorité absolue — pas de fond, currentColor)
    # ⚠️  AJOUTER UN NOUVEAU LOGO BANQUE :
    #   → Déposer le SVG dans static/icons/banks/svg/<slug>.svg
    #   → Le nom = Bank.icon_slug en base
    #   → Le SVG doit utiliser fill="currentColor" (pas de fill="#xxx" hardcodé)
    #   → Pas de rect/fond blanc intégré dans le SVG (à supprimer dans Inkscape si besoin)
    if svg_dir.exists():
        for f in svg_dir.iterdir():
            if (
                f.is_file()
                and not f.name.startswith(".")
                and f.suffix.lower() == ".svg"
            ):
                result[f.stem] = static(f"icons/banks/svg/{f.name}")

    return result


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
    #
    # ECharts accepte un objet LinearGradient dans lineStyle.color :
    #   {"type": "linear", "x": 0, "y": 0, "x2": 1, "y2": 0, "colorStops": [...]}
    # x=0 → bord gauche du flux, x=1 → bord droit.
    #
    # income → pool (gauche → centre) : opacité 0.15 → 0.55
    # pool   → expense (centre → droite) : opacité 0.55 → 0.15
    # Résultat : les flux s'éclaircissent en approchant du pool doré,
    # s'assombrissent en s'en éloignant — sans jamais changer de couleur.

    def _rgba(hex_color: str, alpha: float) -> str:
        """Convertit #rrggbb en rgba(r,g,b,alpha) pour ECharts colorStops."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    def _gradient(hex_color: str, alpha_start: float, alpha_end: float) -> dict:
        """LinearGradient horizontal avec variation d'opacité uniquement."""
        color = hex_color or "#4ade80"
        return {
            "type": "linear",
            "x": 0,
            "y": 0,
            "x2": 1,
            "y2": 0,
            "colorStops": [
                {"offset": 0, "color": _rgba(color, alpha_start)},
                {"offset": 1, "color": _rgba(color, alpha_end)},
            ],
            "global": False,
        }

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
    }

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
    referer = request.META.get("HTTP_REFERER", "")
    return redirect(referer or "budget:index")


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

    referer = request.META.get("HTTP_REFERER", "")
    return redirect(referer or "budget:index")


# =============================================================================
# budget_modal_target_create — Modal HTMX : créer / modifier un objectif mensuel
# =============================================================================


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
    from django.http import HttpResponse

    category_id = request.POST.get("category_id") or request.GET.get("category_id")

    if request.method == "POST":
        category = get_object_or_404(Category, id=category_id)
        amount = request.POST.get("amount", "").replace(",", ".")
        BudgetTarget.objects.update_or_create(
            category=category,
            defaults={"amount": amount},
        )
        response = HttpResponse()
        response["HX-Redirect"] = request.META.get("HTTP_REFERER", "/budget/")
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
    today = date.today()

    # ── Lire la période depuis la session (même logique que budget_index) ──
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
    #
    # Pas de filtre is_ignored=False ici — contrairement à budget_index()
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
        "budget/_panel_tx_list.html",
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
        → "list"   : retourne budget/_panel_tx_row.html  (swap outerHTML sur #tx-id)
        → "detail" : retourne budget/_panel_tx_detail.html (swap innerHTML sur #panel-content)

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
            "budget/_panel_tx_detail.html",
            {"tx": tx, "bank_icon_url": bank_icon_url},
        )

    # source=list (défaut) → appelé depuis la liste → retourner juste la ligne
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
        "budget/_panel_category_picker.html",
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
    # Même logique que budget_panel_rule_create : on utilise la partie avant "|",
    # on écarte le bruit banque (_RULE_NOISE_TOKENS), les nombres, et les codes
    # alphanumériques (lettres + chiffres mélangés comme ESSOF108, PAIEMENT…).
    # Sans ce filtre, "PAIEMENT" (présent dans TOUTES les lignes CIC) serait
    # sélectionné en premier et matcherait l'intégralité de la base.
    description_clean = tx.description_raw.split("|")[0].strip()
    raw_tokens = re.split(r"[\s\*\+\-\/\.\,\_]+", description_clean.upper())
    keyword_tokens = [
        t
        for t in raw_tokens
        if len(t) >= 3
        and not re.search(r"\d", t)  # exclut codes type ESSOF108, 560945
        and re.search(r"[A-Z]", t)  # doit contenir au moins une lettre
        and t not in _RULE_NOISE_TOKENS  # exclut PAIEMENT, PSC, CB, CARTE…
    ]
    keyword = keyword_tokens[0] if keyword_tokens else ""

    response["HX-Trigger"] = json.dumps(
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
    return response


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
        Transaction.objects.select_related("category", "subcategory"),
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
        Transaction.objects.select_related("category", "subcategory"),
        pk=tx_id,
    )

    # Catégorie cible : passée explicitement depuis l'étape intro, ou fallback sur tx.category.
    category = get_object_or_404(Category, pk=cat_id) if cat_id else tx.category
    subcategory = None
    if subcat_id:
        subcategory = SubCategory.objects.filter(pk=subcat_id).first()
    elif tx.subcategory:
        subcategory = tx.subcategory

    # Tokens cliquables — uniquement la partie avant "|" (évite les métadonnées Yuh).
    # Filtre agressif : on garde seulement les tokens qui ont une valeur sémantique
    # (nom de commerce, lieu…) et on écarte le bruit banque (_RULE_NOISE_TOKENS).
    description_clean = tx.description_raw.split("|")[0].strip()
    raw_tokens = re.split(r"[\s\*\+\-\/\.\,\_]+", description_clean.upper())
    seen = set()
    tokens = []
    for t in raw_tokens:
        if (
            len(t) >= 3  # trop court → bruit
            and not re.search(
                r"\d", t
            )  # aucun chiffre → exclut codes type ESSOF108, B560945
            and re.search(r"[A-Z]", t)  # doit contenir au moins une lettre
            and t not in _RULE_NOISE_TOKENS  # liste noire métadonnées banque
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
            Transaction.objects.filter(_keyword_q(keyword))
            .select_related("subcategory")
            .order_by("-date")
        )
        initial_count = qs.count()
        initial_txs = list(qs)  # toutes les transactions — la zone est scrollable

    cat_display_name = subcategory.name if subcategory else category.name

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
        qs = Transaction.objects.filter(_keyword_q(keyword)).order_by("-date")
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

    category = get_object_or_404(Category, pk=cat_id)
    subcategory = SubCategory.objects.filter(pk=sub_id).first() if sub_id else None

    # Compter les transactions affectées SANS les modifier.
    # Toutes les transactions matchant le keyword sont comptées — sans exclusion.
    # Une règle explicite doit pouvoir écraser toute catégorisation antérieure.
    affected_count = Transaction.objects.filter(_keyword_q(keyword)).count()

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

    # Garde serveur : keyword vide → refus silencieux (le bouton est déjà désactivé côté UI)
    if not keyword:
        from django.http import HttpResponseBadRequest

        return HttpResponseBadRequest("keyword requis")

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
    # comme MOT ENTIER (word boundary). Aucune exclusion — une règle explicite écrase
    # toute catégorisation antérieure (import, règle précédente, IA, ou manuelle).
    updated_count = Transaction.objects.filter(
        _keyword_q(keyword),
    ).update(
        category=category,
        subcategory=subcategory,
        categorization_source="rule",
        categorization_rule=rule,
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
        "budget/_panel_tx_detail.html",
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
    Template : budget/_panel_tx_detail.html

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
            "budget/_panel_tx_row.html",
            {"tx": tx, "bank_icon_url": bank_icon_url},
        )

    # source=detail → appelé depuis le panneau détail → retourner le panneau entier
    return render(
        request,
        "budget/_panel_tx_detail.html",
        {"tx": tx, "bank_icon_url": bank_icon_url},
    )


# =============================================================================
def _vary_color(hex_color, factor):
    """Assombrit une couleur hex par un facteur (1.0 = original, 0.4 = 40%).
    Miroir Python de BC.applyFactor en JS (utils.js).
    """
    hex_color = (hex_color or "#4ade80").lstrip("#")
    if len(hex_color) != 6:
        return "#4ade80"
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"#{round(r * factor):02x}{round(g * factor):02x}{round(b * factor):02x}"


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
        return redirect(request.META.get("HTTP_REFERER", "") or "budget:index")

    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    request.session["budget_period_mode"] = "1m"
    request.session["budget_period_start"] = target_date.isoformat()
    request.session["budget_period_end"] = target_date.replace(day=last_day).isoformat()

    referer = request.META.get("HTTP_REFERER", "")
    return redirect(referer or "budget:index")


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

    category = get_object_or_404(Category, slug=slug)

    # ── Période active — même clé session que budget_index ───────────────────
    today = date.today()
    period_start_str = request.session.get("budget_period_start")
    period_end_str = request.session.get("budget_period_end")

    if period_start_str and period_end_str:
        period_start = date.fromisoformat(period_start_str)
        period_end = date.fromisoformat(period_end_str)
    else:
        period_start = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        period_end = today.replace(day=last_day)

    period_mode = request.session.get("budget_period_mode", "1m")
    if period_mode == "1m":
        period_label = f"{MOIS_FR[period_start.month]} {period_start.year}"
    else:
        period_label = (
            f"{MOIS_FR[period_start.month]} — "
            f"{MOIS_FR[period_end.month]} {period_end.year}"
        )

    # Pour le composant period_nav — même logique que budget_index
    current_month_end = date.today().replace(
        day=calendar.monthrange(today.year, today.month)[1]
    )
    can_go_next = period_end < current_month_end

    # ── Transactions de la catégorie sur la période ──────────────────────────
    # On exclut les transactions ignorées — même logique que budget_index.
    txs = (
        Transaction.objects.filter(
            category=category,
            date__gte=period_start,
            date__lte=period_end,
            is_ignored=False,
        )
        .select_related("subcategory", "account", "account__bank")
        .order_by("-date", "-id")
    )

    total_amount = txs.aggregate(total=Sum("amount"))["total"] or 0

    # ── Sous-totaux par sous-catégorie — pour le Sankey + donut ─────────────
    # list() force l'évaluation du queryset ici — on itère deux fois :
    # une fois pour le Sankey, une fois pour le donut.
    subcat_list = list(
        txs.filter(subcategory__isnull=False)
        .values(
            "subcategory__id",
            "subcategory__name",
            "subcategory__slug",
            "subcategory__icon",
        )
        .annotate(total=Sum("amount"))
        .order_by("total")
    )

    # ── Construction du Sankey "direct" (Category → SubCategories) ───────────
    # Nœud source = la catégorie elle-même.
    # Nœuds cibles = les sous-catégories avec des transactions sur la période.
    # Pas de nœud "__pool__" → BricCharts.initSankey détecte hasPool=false
    # et utilise des marges de 10% pour ne pas rogner les labels.
    cat_color = category.colour_hex or "#4ade80"

    # U+200B (zero-width space) : rend le nom du nœud source unique même
    # quand une sous-catégorie porte le même nom que sa catégorie parente
    # (ex: catégorie "Investissements" avec sous-cat "Investissements").
    # ECharts identifie les nœuds par `name` — deux nœuds homonymes créent
    # un self-loop qui rend le chart vide silencieusement.
    # Le ZWSP est invisible à l'affichage et strippé dans le formatter JS.
    source_name = category.name + "​"

    sankey_nodes = [
        {
            "name": source_name,
            "slug": category.slug,
            "itemStyle": {"color": cat_color},
        }
    ]
    sankey_links = []

    # Couleurs pré-calculées : même palette pour Sankey ET donut.
    # _seg_factor distribue les teintes entre 0.70 (lumineux) et 0.15 (sombre)
    # sur n segments — aligné sur le range du gradient Sankey (0.05→0.70).
    n_segs = len(subcat_list)

    def _seg_factor(i, n):
        """Distribue n segments entre 0.70 (lumineux) et 0.35 (sombre min lisible)."""
        if n <= 1:
            return 0.70
        return 0.70 - (0.70 - 0.35) * i / (n - 1)

    subcat_colors = [
        _vary_color(cat_color, _seg_factor(i, n_segs)) for i in range(n_segs)
    ]

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

    sankey_data = {"nodes": sankey_nodes, "links": sankey_links}
    has_sankey = len(sankey_links) > 0

    # ── Distribution donut (panel droit) ────────────────────────────────────
    # subcat_colors calculé au-dessus (même palette que les nœuds Sankey).
    donut_segments = [
        {
            "name": sub["subcategory__name"],
            "value": round(float(abs(sub["total"])), 2),
            "itemStyle": {"color": subcat_colors[i]},
        }
        for i, sub in enumerate(subcat_list)
    ]

    donut_data = {
        "segments": donut_segments,
        "label": "Distribution",
        "sign": "−" if total_amount < 0 else "+",
        "total": round(float(abs(total_amount)), 2),
    }
    has_donut = len(donut_segments) > 0

    # ── Icônes banques pour la liste de transactions ─────────────────────────
    bank_icon_map = _resolve_bank_icon_map()
    for tx in txs:
        icon_slug = tx.account.bank.icon_slug if tx.account and tx.account.bank else ""
        tx.bank_icon_url = bank_icon_map.get(icon_slug, "")

    tx_count = txs.count()
    avg_amount = (total_amount / tx_count) if tx_count > 0 else None

    # ── KPI tabs — données pour les 3 onglets sélecteurs ─────────────────────
    # cat_tab : onglet actif en session (par défaut "transactions")
    cat_tab = request.session.get("budget_cat_tab", "transactions")

    # Nombre de sous-catégories distinctes utilisées sur la période.
    # distinct() sur subcategory_id évite de compter les doublons si plusieurs
    # transactions tombent dans la même sous-catégorie.
    subcat_count = (
        txs.filter(subcategory__isnull=False)
        .values("subcategory_id")
        .distinct()
        .count()
    )

    # Objectif mensuel pour cette catégorie — paramètre général, sans notion de mois.
    # On multiplie par le nombre de mois de la période pour le KPI affiché.
    period_months = PERIOD_MODE_MONTHS.get(period_mode, 1)

    budget_target = BudgetTarget.objects.filter(category=category).first()

    # Montant cible mis à l'échelle de la période + indicateurs de progression
    target_amount = None
    target_pct = None
    on_track = None
    arc_fill_px = None  # longueur de l'arc SVG gauge — approche cercle complet, r=40, demi-périmètre = π×40 = 125.66
    remaining_chf = (
        None  # target_amount - spent : positif = marge, négatif = dépassement
    )
    remaining_abs_chf = None  # abs(remaining_chf) — pour l'affichage sans signe
    if budget_target:
        from decimal import Decimal

        target_amount = budget_target.amount * Decimal(period_months)
        spent = abs(total_amount)
        if target_amount > 0:
            target_pct = round(float(spent / target_amount) * 100)
        else:
            target_pct = 0
        on_track = spent <= target_amount
        # arc_fill_px : proportion de l'arc à remplir.
        # Plafond à 124 (pas 125.5 = périmètre exact) pour laisser un micro-gap :
        # avec stroke-linecap="round", les deux caps arrondis aux extrémités du
        # demi-cercle (10,52) et (90,52) se superposent quand l'arc est plein →
        # deux "oreilles" visibles. En stoppant à 124, le cap de fin n'atteint pas
        # le cap de départ et il n'y a plus de superposition.
        # Demi-périmètre exact : π × r = π × 40 = 125.66
        # Pas besoin de tricher avec 124 — le viewport SVG "0 0 100 52" clippe les oreilles nativement.
        arc_fill_px = round(min(target_pct, 100) / 100 * 125.66, 1)
        # remaining_chf : marge restante (positif) ou dépassement (négatif)
        remaining_chf = round(float(target_amount) - float(spent), 2)
        # remaining_abs_chf : valeur absolue pour l'affichage (|chf| filtre ne gère pas les négatifs)
        remaining_abs_chf = abs(remaining_chf)

    # ── Historique mensuel — 12 mois glissants pour le bar chart ─────────────
    # Indépendant de la période active en session : toujours les 12 derniers mois.
    # Utilisé uniquement dans le tab "objectif" pour visualiser la tendance.
    twelve_months_ago = _add_months(today.replace(day=1), -11)
    monthly_qs = (
        Transaction.objects.filter(
            category=category,
            date__gte=twelve_months_ago,
            date__lte=today,
            is_ignored=False,
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
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
        "target": round(float(budget_target.amount), 2) if budget_target else None,
        # current_month permet à bar.js de colorer la barre active avec la couleur catégorie
        "current_month": period_start.strftime("%Y-%m"),
        # Couleur catégorie — barres actives et ligne objectif
        "cat_color": category.colour_hex or "#4ade80",
    }
    has_history = len(history_months) > 0

    # ── KPI stats sous le bar chart ───────────────────────────────────────────
    # Calculés uniquement si budget_target existe (sinon affichage vide + CTA).
    # Sont des faits fixes sur 12 mois glissants — indépendants de la période.
    bar_kpis = None
    if budget_target and has_history:
        from decimal import Decimal as D

        target_monthly = float(budget_target.amount)

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
        year_spent_agg = Transaction.objects.filter(
            category=category,
            date__gte=year_start,
            date__lte=today,
            is_ignored=False,
        ).aggregate(total=Sum("amount"))["total"] or D(0)
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
            "period_label": period_label,
            "total_amount": total_amount,
            "tx_count": tx_count,
            "avg_amount": avg_amount,
            "txs": txs,
            "subcat_list": subcat_list,
            "sankey_data": sankey_data,
            "has_sankey": has_sankey,
            "donut_data": donut_data,
            "has_donut": has_donut,
            "cat_tab": cat_tab,
            "subcat_count": subcat_count,
            "budget_target": budget_target,
            "target_amount": target_amount,
            "target_pct": target_pct,
            "on_track": on_track,
            "arc_fill_px": arc_fill_px,
            "remaining_chf": remaining_chf,
            "remaining_abs_chf": remaining_abs_chf,
            "period_months": period_months,
            "period_mode": period_mode,
            "period_display": period_label,
            "can_go_next": can_go_next,
            "history_chart_data": history_chart_data,
            "has_history": has_history,
            "bar_kpis": bar_kpis,
        },
    )

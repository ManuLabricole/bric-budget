"""
budget/utils.py — Helpers partagés entre les vues de l'app Budget.

Séparés de views.py pour éviter les imports circulaires lors du split en
views_transactions.py / views_rules.py / views_categories.py.

Aucune vue ici — uniquement des fonctions pures ou quasi-pures.
"""

import calendar
import functools
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.templatetags.static import static
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify

from budget.constants import PERIOD_MODE_MONTHS
from transactions.models import Category, SubCategory


def safe_referer(request, fallback="budget:index"):
    """
    Retourne l'URL du Referer UNIQUEMENT si elle pointe vers notre propre hôte,
    sinon `fallback`. Protège contre les open-redirects (CWE-601) : le Referer
    est envoyé par le client et ne doit jamais être suivi sans validation.

    Usage : `return redirect(safe_referer(request))` dans les vues PRG d'état UI.
    """
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(
        referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return referer
    return fallback


def _period_from_session(session):
    """
    Lit la période active depuis la session Django.
    Retourne (period_start, period_end) — deux objets date.
    Fallback : mois en cours si session vide.
    """
    start_str = session.get("budget_period_start")
    end_str = session.get("budget_period_end")
    if start_str and end_str:
        return date.fromisoformat(start_str), date.fromisoformat(end_str)
    today = date.today()
    return (
        today.replace(day=1),
        today.replace(day=calendar.monthrange(today.year, today.month)[1]),
    )


def _generate_unique_slug(name: str, model_class) -> str:
    """
    Génère un slug unique pour une catégorie ou sous-catégorie.

    Processus :
    1. slugify(name) → minuscules + ASCII + hyphens (ex: "Alimentation et Boissons" → "alimentation-et-boissons")
    2. Remplace les hyphens par underscores pour cohérence avec les slugs système existants
    3. Si le slug existe déjà en DB, ajoute un suffixe numérique (_1, _2, …)

    Paramètres :
        name        : nom saisi par l'utilisateur
        model_class : Category ou SubCategory (les deux ont un champ slug unique)
    """
    base_slug = slugify(name, allow_unicode=False).replace("-", "_")
    slug = base_slug
    counter = 1
    while model_class.objects.filter(slug=slug).exists():
        slug = f"{base_slug}_{counter}"
        counter += 1
    return slug


def _keyword_q(keyword: str):
    r"""
    Retourne un Q filtre Django basé sur le keyword, appliqué sur display_name.

    display_name est le champ stocké nettoyé (bank-agnostic) — c'est lui que
    l'utilisateur voit et sur lequel les règles doivent matcher. description_raw
    reste l'audit trail immuable mais n'est plus la cible du matching.

    Règles :
      - Chaque mot du keyword doit apparaître comme MOT ENTIER dans display_name.
        Ex : keyword="ESSO" ne match pas "ESSOF108" (word boundary \y PostgreSQL).
      - Plusieurs mots → condition AND.
      - Keyword vide → Q(pk__in=[]) pour ne matcher aucune transaction.
    """
    words = [w for w in keyword.upper().split() if w]
    if not words:
        return Q(pk__in=[])
    q = Q()
    for word in words:
        pattern = r"\y" + re.escape(word) + r"\y"
        q &= Q(display_name__iregex=pattern)
    return q


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
# _resolve_institution_icon_map — dict { icon_slug → URL statique }
# =============================================================================


@functools.lru_cache(maxsize=None)
def _resolve_institution_icon_map():
    """
    Construit un dict { icon_slug → URL statique de l'icône institution }.
    lru_cache : les fichiers static ne changent pas entre les requêtes en prod.
    En dev : redémarrer le server si un logo est ajouté.

    Scanne le dossier static/icons/institutions/svg/ — SVGs sans fond, avec fill="currentColor".
    Le SVG currentColor permet d'adapter la couleur de l'icône via CSS (dark theme natif).

    Retourne {} si le dossier n'existe pas (ex: tests sans static).

    Pourquoi svg/ et pas miniature/ ?
        Les PNG dans miniature/ ont un fond blanc intégré dans le fichier → carré blanc
        moche sur dark theme. Les SVG dans svg/ sont des paths purs sans fond — ils
        prennent la couleur CSS de leur conteneur via currentColor.

    ⚠️  AJOUTER UN NOUVEAU LOGO INSTITUTION
        → Déposer le SVG dans static/icons/institutions/svg/<slug>.svg
        → Le nom du fichier doit correspondre à Bank.icon_slug en base
        → Le SVG doit utiliser fill="currentColor" (pas de fill="#xxx" hardcodé)
        → Si le SVG a un fond blanc/coloré intégré : l'enlever dans Inkscape/Figma avant
    """
    base = Path(settings.BASE_DIR) / "static" / "icons" / "institutions"
    svg_dir = base / "svg"
    miniature_dir = base / "miniature"

    # Collecte tous les slugs disponibles dans miniature/ (PNG/JPG = fallback)
    result = {}
    if miniature_dir.exists():
        EXTENSION_PRIORITY = {"svg": 0, "png": 1, "jpg": 2, "jpeg": 3}
        _best: dict[str, tuple[int, str]] = {}
        for f in miniature_dir.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            ext = f.suffix.lstrip(".").lower()
            priority = EXTENSION_PRIORITY.get(ext, 99)
            if f.stem not in _best or priority < _best[f.stem][0]:
                _best[f.stem] = (priority, f.name)
        result = {
            slug: static(f"icons/institutions/miniature/{fname}")
            for slug, (_, fname) in _best.items()
        }

    # Écrase avec les SVG quand disponibles (priorité absolue — pas de fond, currentColor)
    # ⚠️  AJOUTER UN NOUVEAU LOGO INSTITUTION :
    #   → Déposer le SVG dans static/icons/institutions/svg/<slug>.svg
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
                result[f.stem] = static(f"icons/institutions/svg/{f.name}")

    return result


def _rgba(hex_color: str, alpha: float) -> str:
    """Convertit #rrggbb en rgba(r,g,b,alpha) pour ECharts colorStops."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _gradient(hex_color: str, alpha_start: float, alpha_end: float) -> dict:
    """LinearGradient horizontal ECharts avec variation d'opacité uniquement."""
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


def _seg_factor(i, n):
    """Distribue n segments entre 0.70 (lumineux) et 0.35 (sombre min lisible)."""
    if n <= 1:
        return 0.70
    return 0.70 - (0.70 - 0.35) * i / (n - 1)


def _vary_color(hex_color, factor):
    """Assombrit une couleur hex par un facteur (1.0 = original, 0.4 = 40%).
    Miroir Python de BC.applyFactor en JS (utils.js).
    """
    hex_color = (hex_color or "#4ade80").lstrip("#")
    if len(hex_color) != 6:
        return "#4ade80"
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"#{round(r * factor):02x}{round(g * factor):02x}{round(b * factor):02x}"


def _cats_with_subcats():
    """
    Retourne une liste de tuples (Category, [SubCategory, ...]) pour peupler
    le <select> de sous-catégories groupé par catégorie dans les formulaires d'édition.

    Construit en deux passes Python (pas de N+1) :
        1. charger toutes les sous-catégories actives avec leur catégorie
        2. grouper par category_id dans un dict, puis zipper avec les catégories
    """
    all_categories = list(
        Category.objects.filter(is_active=True).order_by("order", "name")
    )
    subcat_by_cat: dict[int, list] = {}
    for sub in (
        SubCategory.objects.filter(is_active=True)
        .select_related("category")
        .order_by("name")
    ):
        subcat_by_cat.setdefault(sub.category_id, []).append(sub)

    return all_categories, [
        (cat, subcat_by_cat.get(cat.id, [])) for cat in all_categories
    ]

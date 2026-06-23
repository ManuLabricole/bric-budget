"""
budget/utils.py — Helpers partagés entre les vues de l'app Budget.

Séparés de views.py pour éviter les imports circulaires lors du split en
views_transactions.py / views_rules.py / views_categories.py.

Aucune vue ici — uniquement des fonctions pures ou quasi-pures.
"""

import calendar
import logging
import re
from datetime import date

from django.db.models import F, Prefetch, Q
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


def _generate_unique_slug(name: str, model_class, owner=None) -> str:
    """
    Génère un slug unique pour une catégorie ou sous-catégorie.

    Processus :
    1. slugify(name) → minuscules + ASCII + hyphens (ex: "Alimentation et Boissons" → "alimentation-et-boissons")
    2. Remplace les hyphens par underscores pour cohérence avec les slugs système existants
    3. Si le slug existe déjà DANS LE SCOPE de l'owner, ajoute un suffixe numérique (_1, _2, …)

    Paramètres :
        name        : nom saisi par l'utilisateur
        model_class : Category ou SubCategory (les deux ont un champ slug owner-scopé)
        owner       : propriétaire de la nouvelle catégorie (#137).
            - owner=None  → catégorie système : slug unique GLOBAL (parmi owner NULL).
            - owner set   → catégorie perso : slug unique PAR USER seulement, donc
              deux users peuvent garder le slug "restaurants" sans suffixe parasite.
              On filtre sur owner pour ne PAS suffixer à cause du slug d'un autre user.
    """
    base_slug = slugify(name, allow_unicode=False).replace("-", "_")
    # Scope d'unicité aligné sur les UniqueConstraint partielles du modèle (#137).
    scope = model_class.objects.filter(owner=owner)
    slug = base_slug
    counter = 1
    while scope.filter(slug=slug).exists():
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


def _cats_with_subcats(user=None):
    """
    Retourne une liste de tuples (Category, [SubCategory, ...]) pour peupler
    le <select> de sous-catégories groupé par catégorie dans les formulaires d'édition.

    `user` (issue #137) : si fourni, scope les catégories/sous-catégories via
    .for_user(user) — l'utilisateur ne voit que les catégories système et SES
    perso, jamais celles d'un autre user. À TOUJOURS passer depuis une vue
    (request.user). None = pas de scoping (chemins internes/tests uniquement).

    Construit en deux passes Python (pas de N+1) :
        1. charger toutes les sous-catégories visibles avec leur catégorie
        2. grouper par category_id dans un dict, puis zipper avec les catégories
    """
    cat_qs = Category.objects.filter(is_active=True)
    sub_qs = SubCategory.objects.filter(is_active=True)
    if user is not None:
        cat_qs = cat_qs.for_user(user)
        sub_qs = sub_qs.for_user(user)

    # SR-001 — fuite inter-user : les templates picker font `cat.subcategories.all`
    # (reverse-FK NON scopée) → une sous-cat perso d'un AUTRE user rattachée à une
    # catégorie système était exposée. On préfetch la reverse-FK avec sub_qs (déjà
    # for_user) → `cat.subcategories.all` ne renvoie plus que système + les miennes.
    cat_qs = cat_qs.prefetch_related(Prefetch("subcategories", queryset=sub_qs))

    all_categories = list(cat_qs.order_by("order", "name"))
    subcat_by_cat: dict[int, list] = {}
    for sub in sub_qs.select_related("category").order_by("name"):
        subcat_by_cat.setdefault(sub.category_id, []).append(sub)

    return all_categories, [
        (cat, subcat_by_cat.get(cat.id, [])) for cat in all_categories
    ]


logger = logging.getLogger(__name__)


def seed_perso_categories(user, defs) -> tuple[int, int]:
    """Crée (idempotent) les catégories/sous-catégories PERSO de `defs` pour `user`.

    `defs` : itérable d'objets (name, slug, icon, parent_slug, colour_hex) — cf.
    demo.profiles.PersoCat. Les top-level (parent_slug=None) sont créées d'abord, puis
    les sous-cats dont le parent est résolu PAR SLUG : catégorie SYSTÈME (owner NULL)
    OU la perso top-level de CE user — jamais celle d'un autre (SR-001/SR-013).

    owner=user + is_system=False → perso scopées (for_user). Clé naturelle
    (slug, owner) → re-run idempotent. Retourne (n_categories, n_sous_categories).
    Réutilisable hors démo (seed prod de l'admin via une commande, incrément 2).
    """
    from transactions.models import Category, SubCategory

    n_cat = n_sub = 0
    for d in defs:
        if d.parent_slug is not None:
            continue
        Category.objects.update_or_create(
            slug=d.slug,
            owner=user,
            defaults={
                "name": d.name,
                "icon": d.icon,
                "colour_hex": d.colour_hex,
                "is_system": False,
                "is_active": True,
            },
        )
        n_cat += 1

    for d in defs:
        if d.parent_slug is None:
            continue
        # Préférer le parent PERSO du user (owner=user) au parent SYSTÈME de même slug :
        # sans tri, .first() peut rattacher la sous-cat au mauvais arbre (parent système)
        # alors qu'un parent perso homonyme existe. nulls_last → perso (non-null) d'abord.
        parent = (
            Category.objects.filter(slug=d.parent_slug)
            .filter(Q(owner__isnull=True) | Q(owner=user))
            .order_by(F("owner").asc(nulls_last=True))
            .first()
        )
        if parent is None:
            logger.warning(
                "seed_perso_categories: parent slug=%s introuvable pour sous-cat=%s",
                d.parent_slug,
                d.slug,
            )
            continue
        SubCategory.objects.update_or_create(
            slug=d.slug,
            owner=user,
            defaults={
                "name": d.name,
                "icon": d.icon,
                "category": parent,
                "is_system": False,
                "is_active": True,
            },
        )
        n_sub += 1

    return n_cat, n_sub

"""
patrimoine/services/chart_data.py — sérialisation JSON pour la courbe et la distribution.

Consomme `valuation` (net worth) et `bilan` (BilanNode), et produit des dicts prêts pour
`json_script` (consommés par balance.js / donut.js / treemap.js). Decimal en interne,
`float()` uniquement à la frontière JSON (SR-002).

⚠️ Sécurité (SR-001) : `accounts` déjà scopés for_user (cf. valuation/bilan).

Fonctions :
  chart_series           — courbe net worth multi-classes (vue overview)
  account_class_series   — courbe par compte dans une classe (vue asset_class)
  distribution           — segments donut/treemap (overview + asset_class)
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from .asset_classes import ASSET_CLASSES, asset_class_for_account_type
from .bilan import BilanNode
from .valuation import net_worth_series


def chart_series(
    accounts,
    start: datetime.date,
    end: datetime.date,
    selected_slugs: set[str] | None = None,
) -> dict:
    """
    Données de la courbe net worth : total + une série par classe d'actifs fonctionnelle.

    Seuls les comptes des classes fonctionnelles sont tracés (les classes invest ne sont
    pas encore valorisables). `complete=False` signale une conversion CHF manquante.
    `selected_slugs` : si fourni, ne trace que ces classes (filtre).
    """
    # Un seul passage : on mémorise l'asset_class résolue pour éviter le double appel.
    functional_accounts = []
    _ac_for: dict = {}
    for a in accounts:
        ac = asset_class_for_account_type(a.account_type)
        if (
            ac is not None
            and ac.functional
            and (selected_slugs is None or ac.slug in selected_slugs)
        ):
            functional_accounts.append(a)
            _ac_for[a.pk] = ac
    by_class: dict[str, list] = defaultdict(list)
    for a in functional_accounts:
        by_class[_ac_for[a.pk].slug].append(a)

    total = net_worth_series(functional_accounts, start, end)
    series = []
    for ac in ASSET_CLASSES:
        accs = by_class.get(ac.slug)
        if not ac.functional or not accs:
            continue
        s = net_worth_series(accs, start, end)
        series.append(
            {
                "name": ac.label,
                "color": ac.color,
                "values": [float(v) for v in s.values],
            }
        )

    return {
        "dates": [d.isoformat() for d in total.dates],
        "total": [float(v) for v in total.values],
        "series": series,
        "anchored": total.anchored,
        "complete": total.complete,
    }


# Filet de sécurité pour différencier les comptes dans le mode empilé QUAND un
# compte n'a pas de colour_hex stockée (créé hors create_account ou pas encore
# backfillé). La vraie couleur stable vit en DB (Account.colour_hex, #134) ; ce
# tableau ne sert plus que de fallback déterministe (ordre fixe) pour ne JAMAIS
# rendre une série sans couleur.
_STACK_PALETTE = (
    "#5fae9f",
    "#5d6bf0",
    "#9b7ae8",
    "#e58d88",
    "#b06bb0",
    "#3d8b7a",
    "#7a8df0",
    "#c88fe8",
)


def account_color(account, index: int) -> str:
    """
    Couleur stable d'un compte dans les charts patrimoine (#134).

    Source de vérité = `Account.colour_hex` (allouée à la création puis figée).
    Fallback `_STACK_PALETTE[index % len]` si le champ est vide (compte non
    backfillé ou créé hors create_account) — garde-fou : jamais de série sans
    couleur. Helper partagé par la courbe (account_class_series) ET les
    pastilles/treemap de la vue asset_class, pour que les 3 restent alignés.
    """
    return account.colour_hex or _STACK_PALETTE[index % len(_STACK_PALETTE)]


def account_class_series(
    accounts,
    start: datetime.date,
    end: datetime.date,
) -> dict:
    """
    Données courbe pour une classe d'actifs : total CHF + une série CHF par compte.

    Utilisé par la page asset_class (comptes courants, livrets). Les comptes doivent
    être pré-scopés for_user (SR-001) par l'appelant — ce service ne vérifie pas.
    """
    from .balance_history import account_balance_series

    accounts = list(accounts)
    n_days = (end - start).days + 1

    if not accounts:
        dates = [start + datetime.timedelta(days=i) for i in range(n_days)]
        return {
            "dates": [d.isoformat() for d in dates],
            "total": [0.0] * n_days,
            "series": [],
            "anchored": False,
            "complete": True,
        }

    # Séries individuelles en CHF (cohérence multi-devises pour le stacking).
    per_account = [
        account_balance_series(acc, start, end, in_chf=True) for acc in accounts
    ]
    dates = per_account[0].dates
    n = len(dates)

    total = [float(sum(s.values[i] for s in per_account)) for i in range(n)]
    series = [
        {
            "name": acc.name,
            "color": account_color(acc, i),
            "values": [float(v) for v in per_account[i].values],
        }
        for i, acc in enumerate(accounts)
    ]

    return {
        "dates": [d.isoformat() for d in dates],
        "total": total,
        "series": series,
        "anchored": any(s.anchored for s in per_account),
        "complete": all(s.complete for s in per_account),
    }


def single_account_series(
    account,
    start: datetime.date,
    end: datetime.date,
) -> dict:
    """
    Données courbe pour UN seul compte (page zoom compte).

    Pas de stacking (un seul compte) : `total` = sa série CHF, `series` vide → la
    courbe rend la ligne gold standard (cf. balance.js mode standard). Le compte doit
    être pré-scopé for_user (SR-001) par l'appelant — ce service ne vérifie pas.
    """
    from .balance_history import account_balance_series

    s = account_balance_series(account, start, end, in_chf=True)
    return {
        "dates": [d.isoformat() for d in s.dates],
        "total": [float(v) for v in s.values],
        "series": [],
        "anchored": s.anchored,
        "complete": s.complete,
    }


def distribution(nodes: list[BilanNode]) -> dict:
    """
    Données de répartition (donut ET treemap) à partir des nœuds de bilan de niveau 1.
    Shape ECharts (`itemStyle.color`, comme le donut budget). Exclut les nœuds sans
    valeur connue ou à 0 (SOON, vides). `label`/`sign` = texte central du donut.
    """
    segments = [
        {"name": n.label, "value": float(n.value), "itemStyle": {"color": n.color}}
        for n in nodes
        if n.value is not None and n.value > Decimal("0")
    ]
    return {
        "segments": segments,
        "total": sum(s["value"] for s in segments),
        "label": "Patrimoine",
        "sign": "",
    }

"""
patrimoine/services/chart_data.py — sérialisation JSON pour la courbe et la distribution.

Consomme `valuation` (net worth) et `bilan` (BilanNode), et produit des dicts prêts pour
`json_script` (consommés par balance.js / donut.js / treemap.js). Decimal en interne,
`float()` uniquement à la frontière JSON (SR-002).

⚠️ Sécurité (SR-001) : `accounts` déjà scopés for_user (cf. valuation/bilan).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from .asset_classes import ASSET_CLASSES, asset_class_for_account_type
from .bilan import BilanNode
from .valuation import net_worth_series


def chart_series(accounts, start: datetime.date, end: datetime.date) -> dict:
    """
    Données de la courbe net worth : total + une série par classe d'actifs fonctionnelle.

    Seuls les comptes des classes fonctionnelles sont tracés (les classes invest ne sont
    pas encore valorisables). `complete=False` signale une conversion CHF manquante.
    """
    functional_accounts = [
        a
        for a in accounts
        if (ac := asset_class_for_account_type(a.account_type)) is not None
        and ac.functional
    ]
    by_class: dict[str, list] = defaultdict(list)
    for a in functional_accounts:
        ac = asset_class_for_account_type(a.account_type)
        assert ac is not None  # garanti par le filtre ci-dessus
        by_class[ac.slug].append(a)

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

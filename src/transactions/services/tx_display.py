"""
transactions/services/tx_display.py — annotation batch des icônes d'affichage.

Un seul point pour poser `tx.institution_icon_url` + `tx.merchant_logo_url` sur
une liste de transactions avant rendu (_panel_tx_row.html). Avant ce module,
chaque vue listant des transactions (budget.views.transactions,
budget.views.categories, patrimoine.views.account_detail,
patrimoine.views.asset_class) dupliquait le même double-lookup — constaté x4
pour l'icône institution seule, aurait doublé à x8 en copiant aussi la
résolution marchand plutôt que de l'extraire ici (repérage réel : le badge
marchand n'apparaissait QUE dans le panel "Tout voir" — budget.views.transactions
est le seul appelant à avoir reçu le lookup marchand à la main, #124).

1 scan disque (manuel) + N regex (seed) + 1 scan disque (institutions), peu importe
la taille de la liste — anti-N+1 (mêmes services.logos.get_institution_icon_map
et services.merchant_logos.get_merchant_logo_map déjà cachés en amont).
"""

from __future__ import annotations

from typing import Any

from services.logos import get_institution_icon_map
from services.merchant_logos import get_merchant_logo_map


def annotate_tx_display_icons(transactions: Any) -> list[Any]:
    """
    Pose `.institution_icon_url` et `.merchant_logo_url` sur chaque tx (mutation en
    place) et retourne la liste matérialisée — pratique pour l'appelant qui a
    juste besoin de `tx_list = annotate_tx_display_icons(qs)`.

    `Any` plutôt que `Iterable[Transaction]` : ces deux attributs n'existent pas sur
    le modèle (posés dynamiquement pour le template _panel_tx_row.html) — même
    typage effectif que les call sites historiques, où `tx` transite par un
    Paginator non typé et devient Any pour mypy.

    Chaque tx doit être select_related("account", "account__institution") — sinon
    l'accès à tx.account.institution déclenche du N+1 (non détecté ici, à la charge
    de l'appelant, comme avant l'extraction).
    """
    tx_list = list(transactions)
    institution_icon_map = get_institution_icon_map()
    merchant_logo_map = get_merchant_logo_map([tx.display_name for tx in tx_list])
    for tx in tx_list:
        slug = (
            tx.account.institution.icon_slug
            if tx.account and tx.account.institution
            else ""
        )
        tx.institution_icon_url = institution_icon_map.get(slug, "")
        tx.merchant_logo_url = merchant_logo_map.get(tx.display_name, "")
    return tx_list

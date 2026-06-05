"""
patrimoine/services/asset_classes.py — les classes d'actifs du patrimoine.

Une **classe d'actifs** (`AssetClass`) est une rubrique par laquelle on navigue le
patrimoine : Comptes courants, Livrets, Actions & Fonds, Fonds euros, Crypto.
C'est le vocabulaire d'allocation (au sens large, le cash EST une classe d'actifs) —
à ne pas confondre avec :
  - `transactions.Category` → classification budgétaire des DÉPENSES,
  - `Account.account_type` → discriminateur technique du sous-type de compte.

Pas de modèle DB : patrimoine/ agrège accounts + transactions au runtime (Phase 3A).
Le registre est un mapping statique Python — la vérité vit dans le code, pas en base.

Lien classe → account_type
---------------------------
Pour les classes FONCTIONNELLES (liquidités), le lien est 1:1 et fiable :
    comptes-courants → checking,  livrets → savings.
Pour les classes SOON (investissement), `account_types` est **provisoire** : à terme
une AV portera *fonds euros ET unités de compte* via des positions (Phase 5+), pas
via son `account_type`. On ne s'appuie sur ce mapping que pour les classes fonctionnelles.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetClass:
    """Une rubrique de navigation du patrimoine."""

    slug: str  # segment d'URL : /patrimoine/<slug>/
    label: str  # libellé affiché dans la sidebar
    account_types: tuple[str, ...]  # Account.account_type rattachés (cf. note module)
    functional: bool  # False → page rendue en état SOON, jamais de listing/404
    color: (
        str  # token hex — source de vérité couleur (donut, courbe, pastille de ligne)
    )


# Ordre = ordre d'affichage dans la sidebar (liquidités d'abord, puis investissement).
# Couleurs : alignées sur la logique de la palette catégories (budget/constants.py).
ASSET_CLASSES: tuple[AssetClass, ...] = (
    AssetClass("comptes-courants", "Comptes courants", ("checking",), True, "#5abdc5"),
    AssetClass("livrets", "Livrets", ("savings",), True, "#7ec8e3"),
    AssetClass(
        "actions-fonds",
        "Actions & Fonds",
        ("brokerage", "investment"),
        False,
        "#b09be8",
    ),
    AssetClass("fonds-euros", "Fonds euros", ("insurance",), False, "#e77f79"),
    AssetClass("crypto", "Crypto", ("crypto",), False, "#deab5e"),
)

# Index slug → AssetClass pour des lookups O(1) (les slugs sont uniques, cf. tests).
_BY_SLUG: dict[str, AssetClass] = {ac.slug: ac for ac in ASSET_CLASSES}
# Index account_type → AssetClass (chaque account_type appartient à une seule classe).
_BY_ACCOUNT_TYPE: dict[str, AssetClass] = {
    at: ac for ac in ASSET_CLASSES for at in ac.account_types
}


def get_asset_class(slug: str) -> AssetClass | None:
    """Retourne la classe d'actifs pour un slug, ou None si inconnu (→ 404 en vue)."""
    return _BY_SLUG.get(slug)


def asset_class_for_account_type(account_type: str) -> AssetClass | None:
    """Classe d'actifs d'un account_type (ex. 'checking' → comptes-courants), ou None."""
    return _BY_ACCOUNT_TYPE.get(account_type)

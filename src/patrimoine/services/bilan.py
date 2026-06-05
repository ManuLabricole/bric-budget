"""
patrimoine/services/bilan.py — arbre de bilan (la grammaire réutilisée partout).

Un bilan = une liste de `BilanNode` (récursif). Niveau 1 paramétré par la dimension :
overview → AssetClass, page classe → Institution (à venir). Chaque nœud porte ses KPIs
(valeur CHF, part du grand total, +/- value) et une `url` (label cliquable → page zoom).

⚠️ Sécurité (SR-001) : les comptes passés ici sont DÉJÀ scopés `for_user` (cf. valuation).

Décisions (design_patrimoine_bilan) :
  - value/share en `Decimal` (SR-002), CHF. value=None = inconnu (sans ancre) ou SOON.
  - delta (+/- value latente) = None pour le cash → SOON, fourni plus tard par la phase Asset.
  - classes non fonctionnelles (invest) → nœud SOON (soon=True).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.urls import reverse

from .asset_classes import ASSET_CLASSES, asset_class_for_account_type
from .valuation import current_value

# Précision d'affichage des parts (%).
_SHARE_Q = Decimal("0.01")


@dataclass
class BilanNode:
    """Une ligne de bilan, récursive. `url` = lien du label vers la page zoom."""

    label: str
    color: str
    value: Decimal | None  # CHF ; None = inconnu (sans ancre) ou SOON
    share: Decimal | None = None  # % du grand total ; None si valeur inconnue
    delta: Decimal | None = None  # +/- value latente ; None = SOON (cash)
    url: str | None = None  # cible du lien (None = ligne non cliquable)
    soon: bool = False  # classe pas encore fonctionnelle
    currency_native: str | None = None
    # Institution du holding (nœud compte) → logo dans la ligne. None pour un nœud de classe.
    institution: object | None = None
    children: list["BilanNode"] = field(default_factory=list)


def overview_bilan(accounts, on: datetime.date | None = None) -> list[BilanNode]:
    """
    Arbre bilan de l'overview : un nœud par classe d'actifs (registre), enfants = comptes.

    `accounts` : liste plate de comptes DÉJÀ scopés for_user. Les classes fonctionnelles
    sont valorisées (via `current_value`) ; les autres sont rendues en SOON.
    """
    by_class: dict[str, list] = defaultdict(list)
    for acc in accounts:
        ac = asset_class_for_account_type(acc.account_type)
        if ac is not None:
            by_class[ac.slug].append(acc)

    nodes: list[BilanNode] = []
    for ac in ASSET_CLASSES:
        url = reverse("patrimoine:asset_class", args=[ac.slug])
        if not ac.functional:
            # Classe pas encore prête : SOON, même si des comptes existent (non valorisables).
            nodes.append(
                BilanNode(
                    label=ac.label, color=ac.color, value=None, url=url, soon=True
                )
            )
            continue

        children = [
            BilanNode(
                label=acc.name,
                color=ac.color,
                value=current_value(acc, on),
                currency_native=acc.currency,
                institution=acc.institution,  # → logo dans la ligne
                # url enfant (zoom compte) → PR C : None pour l'instant.
            )
            for acc in by_class.get(ac.slug, [])
        ]
        # Valeur de la classe = somme des valeurs CONNUES des comptes (None ignoré).
        value = sum((c.value for c in children if c.value is not None), Decimal("0"))
        nodes.append(
            BilanNode(
                label=ac.label, color=ac.color, value=value, url=url, children=children
            )
        )

    _fill_shares(nodes)
    return nodes


def _fill_shares(nodes: list[BilanNode]) -> None:
    """Calcule la part (%) de chaque nœud et enfant par rapport au grand total connu."""
    grand = sum((n.value for n in nodes if n.value is not None), Decimal("0"))
    if not grand:
        return
    for n in nodes:
        if n.value is not None:
            n.share = (n.value / grand * 100).quantize(_SHARE_Q)
        for child in n.children:
            if child.value is not None:
                child.share = (child.value / grand * 100).quantize(_SHARE_Q)

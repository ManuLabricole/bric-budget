"""
patrimoine/services/valuation.py — frontière stable de valorisation.

C'est la SEULE porte d'entrée des vues et du service `bilan` vers la valeur d'un
compte ou le net worth d'un ensemble de comptes. Aujourd'hui l'implémentation
calcule à la volée via le moteur `balance_history`. Demain on pourra lire des
`PortfolioSnapshot` matérialisés (issue #92, scalabilité) SANS changer un seul
appelant — c'est tout l'intérêt de cette frontière (cf. design_patrimoine_bilan §4).

⚠️ Sécurité (SR-001) : les comptes passés ici DOIVENT déjà être scopés
`Account.objects.for_user(request.user)`. Ces fonctions ne vérifient pas
l'appartenance (mêmes contrats que `balance_history`).

Tout en `Decimal` (SR-002). Devise de référence : CHF.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.utils import timezone

from .balance_history import (
    BalanceSeries,
    account_balance_series,
    consolidated_balance_series,
)


def current_value(account, on: datetime.date | None = None) -> Decimal | None:
    """
    Valeur CHF d'un compte à la date `on` (défaut : aujourd'hui).

    Retourne None quand la valeur n'est pas fiable :
      - compte sans ancre (aucun snapshot) → solde absolu inconnu,
      - conversion CHF manquante (balance_chf NULL, taux pas encore calculé).
    Jamais un 0 inventé : l'appelant décide quoi afficher (« — » / SOON).
    """
    on = on or timezone.localdate()
    series = account_balance_series(account, on, on, in_chf=True)
    if not series.anchored or not series.complete:
        return None
    return series.values[0]


def net_worth_series(
    accounts, start: datetime.date, end: datetime.date
) -> BalanceSeries:
    """Série net worth (somme CHF) d'un ensemble de comptes entre start et end."""
    return consolidated_balance_series(accounts, start, end)

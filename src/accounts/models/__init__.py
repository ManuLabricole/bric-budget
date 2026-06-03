"""
accounts/models/ — Banking infrastructure for BricBudget

Fichiers :
    institution.py  — Institution (banque, fondation, exchange…)
    account.py      — Account (enveloppe générique) + AccountQuerySet
    details.py      — CheckingAccount, SavingsAccount, LifeInsuranceDetails,
                      PensionDetails  (tous les OneToOne → Account)
    card.py         — Card (FK → CheckingAccount, pas Account)
    snapshot.py     — BalanceSnapshot
    fx.py           — ExchangeRate
"""

from .account import Account, AccountQuerySet
from .card import Card
from .details import (
    CheckingAccount,
    LifeInsuranceDetails,
    PensionDetails,
    SavingsAccount,
)
from .fx import ExchangeRate
from .institution import Institution
from .snapshot import BalanceSnapshot

__all__ = [
    "Account",
    "AccountQuerySet",
    "BalanceSnapshot",
    "Card",
    "CheckingAccount",
    "ExchangeRate",
    "Institution",
    "LifeInsuranceDetails",
    "PensionDetails",
    "SavingsAccount",
]

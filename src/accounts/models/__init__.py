"""
accounts/models/ — Banking infrastructure for BricBudget

Model dependency order (follow this when reading or extending):
    Bank → Account → CheckingAccount → Card (→ User)
                   → BalanceSnapshot
    ExchangeRate (standalone)

Éclaté en package (Phase 3A) : un fichier par contexte. Tous les modèles sont
ré-exportés ici → `from accounts.models import X` continue de fonctionner
partout (vues, resolver, migrations, admin, tests). Les migrations 0001-0014
référencent les modèles par (app_label, model_name) via apps.get_model — le
split en package ne les touche pas.
"""

from .account import Account, AccountQuerySet
from .bank import Bank
from .fx import ExchangeRate
from .snapshot import BalanceSnapshot
from .specialisations import Card, CheckingAccount, SavingsAccount

__all__ = [
    "Account",
    "AccountQuerySet",
    "BalanceSnapshot",
    "Bank",
    "Card",
    "CheckingAccount",
    "ExchangeRate",
    "SavingsAccount",
]

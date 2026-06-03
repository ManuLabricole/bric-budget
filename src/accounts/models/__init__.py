"""
accounts/models/ — Banking infrastructure for BricBudget

Model dependency order (follow this when reading or extending):
    Institution → Account → CheckingAccount → Card (→ User)
                          → BalanceSnapshot
    ExchangeRate (standalone)

Éclaté en package (Phase 3A) : un fichier par contexte. Tous les modèles sont
ré-exportés ici → `from accounts.models import X` continue de fonctionner
partout (vues, resolver, migrations, admin, tests). Les migrations 0001-0014
référencent les modèles par (app_label, model_name) via apps.get_model — le
split en package ne les touche pas.
"""

from .account import Account, AccountQuerySet
from .details import LifeInsuranceDetails, PensionDetails
from .fx import ExchangeRate
from .institution import Institution
from .snapshot import BalanceSnapshot
from .specialisations import Card, CheckingAccount, SavingsAccount

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

"""
accounts/services/builders.py — upsert des sous-modèles *Details par type.

Partagé par create_account (la ligne *Details n'existe pas encore → get_or_create
l'insère) ET update_account (elle existe → on la met à jour). Un seul jeu de
builders : pour une création, le get_or_create insère ; pour une édition, il
récupère la ligne existante. full_clean() est appelé AVANT save (la forme DB —
max_digits, longueurs — est validée), et un échec annule l'Account grâce au
transaction.atomic() de l'appelant.

Convention : champ ABSENT de `fields` ⇒ on n'y touche pas (édition partielle —
ex. un savings sans IBAN au form ne doit pas écraser interest_rate). Champ
présent à None ⇒ on écrit None (nullable) ou le défaut NOT NULL.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from ..models import (
    Account,
    CheckingAccount,
    LifeInsuranceDetails,
    PensionDetails,
    SavingsAccount,
)


def _build_checking(account: Account, fields: dict[str, Any]) -> None:
    # L'IBAN est posé sur account.iban par l'appelant (source unique #82) ;
    # CheckingAccount ne porte plus que le BIC.
    details, _ = CheckingAccount.objects.get_or_create(account=account)
    if "bic" in fields:
        details.bic = fields.get("bic") or ""
    details.full_clean()
    details.save()


def _build_savings(account: Account, fields: dict[str, Any]) -> None:
    details, _ = SavingsAccount.objects.get_or_create(account=account)
    if "interest_rate" in fields:
        rate = fields.get("interest_rate")
        # NOT NULL (default=0) : None ne doit pas partir en DB.
        details.interest_rate = Decimal("0") if rate is None else rate
    if "account_reference" in fields:
        details.account_reference = fields.get("account_reference") or ""
    details.full_clean()
    details.save()


def _build_insurance(account: Account, fields: dict[str, Any]) -> None:
    details, _ = LifeInsuranceDetails.objects.get_or_create(account=account)
    for attr in ("fonds_euro_balance", "fonds_euro_rate", "management_fee_pct"):
        if attr in fields:
            setattr(details, attr, fields.get(attr))
    details.full_clean()
    details.save()


def _build_pension(account: Account, fields: dict[str, Any]) -> None:
    details, _ = PensionDetails.objects.get_or_create(account=account)
    for attr in ("annual_limit_chf", "contributions_ytd", "management_fee_pct"):
        if attr in fields:
            setattr(details, attr, fields.get(attr))
    details.full_clean()
    details.save()


# Dispatch type → builder. Types absents (investment, brokerage, crypto, card) :
# Account seul, aucun sous-modèle — c'est voulu (pas de Details à ce jour).
DETAILS_BUILDERS: dict[str, Callable[[Account, dict[str, Any]], None]] = {
    Account.AccountType.CHECKING: _build_checking,
    Account.AccountType.SAVINGS: _build_savings,
    Account.AccountType.INSURANCE: _build_insurance,
    Account.AccountType.PENSION_3A: _build_pension,
    Account.AccountType.PENSION_LP: _build_pension,
}

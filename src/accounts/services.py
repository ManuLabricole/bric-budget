"""
accounts/services.py — services métier de l'app accounts.

create_account() : LE point d'entrée de création d'une enveloppe depuis l'UI
(wizard #73, D-026/D-028). Orchestration uniquement — les invariants de champ
restent sur les modèles (Account.clean() : pension ⇒ CHF) et sont appliqués via
full_clean(), parce que objects.create() ne déclenche PAS clean().

Convention : fichier plat tant qu'il n'y a qu'un seul service ; au 2e service,
convertir en package accounts/services/ (comme patrimoine/services/).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from users.models import CustomUser

from .models import (
    Account,
    CheckingAccount,
    Institution,
    LifeInsuranceDetails,
    PensionDetails,
    SavingsAccount,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Builders — un par sous-modèle *Details (full_clean systématique : la forme
# DB — max_digits, longueurs, unicité — est validée AVANT l'écriture, et un
# échec ici annule aussi l'Account grâce au transaction.atomic() de l'appelant).
# =============================================================================


def _build_checking(account: Account, fields: dict[str, Any]) -> None:
    # L'IBAN est déjà posé sur account.iban par create_account (source unique #82) ;
    # CheckingAccount ne porte plus que le BIC.
    details = CheckingAccount(
        account=account,
        bic=fields.get("bic") or "",
    )
    details.full_clean()
    details.save()


def _build_savings(account: Account, fields: dict[str, Any]) -> None:
    rate = fields.get("interest_rate")
    details = SavingsAccount(
        account=account,
        # NOT NULL (default=0) : None ne doit pas partir en DB.
        interest_rate=Decimal("0") if rate is None else rate,
        account_reference=fields.get("account_reference") or "",
    )
    details.full_clean()
    details.save()


def _build_insurance(account: Account, fields: dict[str, Any]) -> None:
    details = LifeInsuranceDetails(
        account=account,
        fonds_euro_balance=fields.get("fonds_euro_balance"),
        fonds_euro_rate=fields.get("fonds_euro_rate"),
        management_fee_pct=fields.get("management_fee_pct"),
    )
    details.full_clean()
    details.save()


def _build_pension(account: Account, fields: dict[str, Any]) -> None:
    details = PensionDetails(
        account=account,
        annual_limit_chf=fields.get("annual_limit_chf"),
        contributions_ytd=fields.get("contributions_ytd"),
        management_fee_pct=fields.get("management_fee_pct"),
    )
    details.full_clean()
    details.save()


# Dispatch type → builder. Types absents (investment, brokerage, crypto, card) :
# Account seul, aucun sous-modèle — c'est voulu (pas de Details à ce jour).
_DETAILS_BUILDERS: dict[str, Callable[[Account, dict[str, Any]], None]] = {
    Account.AccountType.CHECKING: _build_checking,
    Account.AccountType.SAVINGS: _build_savings,
    Account.AccountType.INSURANCE: _build_insurance,
    Account.AccountType.PENSION_3A: _build_pension,
    Account.AccountType.PENSION_LP: _build_pension,
}


def create_account(
    *,
    user: CustomUser,
    institution: Institution,
    account_type: str,
    name: str,
    currency: str,
    contract_number: str = "",
    opened_at: date | None = None,
    **type_fields: Any,
) -> Account:
    """
    Crée une enveloppe complète : Account + *Details du type + membership.

    Lève ValidationError si un invariant modèle est violé (type inconnu,
    pension hors CHF, IBAN dupliqué…) — rien n'est alors persisté (atomique).
    `type_fields` : champs propres au type (iban, bic, interest_rate…), déjà
    castés par l'appelant (Decimal/str) — aucun parsing ici.
    """
    # Identité d'import obligatoire (décision 2026-06-12) : sans IBAN ni n° de
    # contrat, le compte ne pourra JAMAIS être rattaché à un relevé importé.
    iban = (type_fields.get("iban") or "").strip()
    if not iban and not contract_number.strip():
        raise ValidationError(
            "Renseigne l'IBAN ou le n° de contrat — c'est ce qui rattache "
            "les imports de relevés à ce compte."
        )

    with transaction.atomic():
        account = Account(
            institution=institution,
            name=name,
            account_type=account_type,
            currency=currency,
            opened_at=opened_at,
            # Identité de résolution des imports = Account.iban | contract_number
            # (décision 2026-06-10) ; iban "" → None sinon collision unique sur
            # le 2e compte sans IBAN. contract_number vaut pour TOUS les types
            # (livret, AV, 3a… : souvent le seul identifiant exporté).
            iban=type_fields.get("iban") or None,
            contract_number=contract_number.strip(),
        )
        account.full_clean()
        account.save()
        account.members.add(user)  # sans membre, invisible via for_user() (SR-001)

        builder = _DETAILS_BUILDERS.get(account_type)
        if builder is not None:
            builder(account, type_fields)

    logger.info(
        "create_account ok id=%s institution=%s type=%s user=%s",
        account.pk,
        institution.slug,
        account_type,
        user.pk,
    )
    return account

"""
accounts/services/update.py — édition & archivage d'une enveloppe (#292).

update_account() : miroir de create_account pour l'ÉDITION depuis la page compte
(panel « Détails du compte »). Le type de compte et l'institution sont en lecture
seule (changer le type = muter le OneToOne de spécialisation, hors scope #82).

archive_account() : soft-delete (is_active=False) — le compte sort des listes
(for_user().filter(is_active=True)) mais transactions/imports/snapshots restent
en base, réversible. Pas de suppression dure (FK PROTECT + perte de données).
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import Account
from .builders import DETAILS_BUILDERS

logger = logging.getLogger(__name__)


def update_account(
    *,
    account: Account,
    name: str,
    currency: str,
    contract_number: str = "",
    **type_fields: Any,
) -> Account:
    """
    Met à jour une enveloppe existante : champs Account + *Details du type.

    Lève ValidationError sur invariant violé (pension hors CHF, IBAN dupliqué,
    longueurs…) — rien n'est alors persisté (atomique). `type_fields` est déjà
    casté par l'appelant ; un champ ABSENT n'est pas touché (édition partielle,
    cf. builders) — en particulier l'IBAN n'est écrasé que s'il est dans le form.
    """
    with transaction.atomic():
        account.name = name
        account.currency = currency
        account.contract_number = contract_number.strip()
        # IBAN modifié seulement s'il fait partie du formulaire de ce type
        # (checking). Pour savings (pas de champ IBAN au form à ce jour), on
        # garde la valeur DB — ne JAMAIS l'effacer par omission.
        if "iban" in type_fields:
            account.iban = type_fields.get("iban") or None

        # Identité d'import obligatoire (décision 2026-06-12) : on vérifie sur la
        # valeur EFFECTIVE (IBAN nouvellement saisi ou conservé) — un compte ne
        # peut pas se retrouver sans IBAN ET sans n° de contrat.
        if not (account.iban or "").strip() and not account.contract_number:
            raise ValidationError(
                "Renseigne l'IBAN ou le n° de contrat — c'est ce qui rattache "
                "les imports de relevés à ce compte."
            )

        # full_clean() revalide l'unicité de l'IBAN en excluant le pk courant
        # (instance déjà persistée) → modifier sans changer l'IBAN ne lève pas.
        account.full_clean()
        account.save(update_fields=["name", "currency", "iban", "contract_number"])

        builder = DETAILS_BUILDERS.get(account.account_type)
        if builder is not None:
            builder(account, type_fields)

    logger.info(
        "update_account ok id=%s type=%s",
        account.pk,
        account.account_type,
    )
    return account


def archive_account(account: Account) -> None:
    """Soft-delete : is_active=False. Le compte disparaît des listes for_user."""
    account.is_active = False
    account.save(update_fields=["is_active"])
    logger.info("archive_account ok id=%s", account.pk)

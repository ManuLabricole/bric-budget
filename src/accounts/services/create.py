"""
accounts/services/create.py — création d'une enveloppe (wizard #73, D-026/D-028).

create_account() : LE point d'entrée de création depuis l'UI. Orchestration
uniquement — les invariants de champ restent sur les modèles (Account.clean() :
pension ⇒ CHF) et sont appliqués via full_clean(), parce que objects.create()
ne déclenche PAS clean().
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from services.colors import allocate_color
from users.models import CustomUser

from ..models import Account, Institution
from .builders import DETAILS_BUILDERS

logger = logging.getLogger(__name__)


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

        # Couleur stable du compte dans les charts patrimoine (#134). Domaine
        # d'allocation = les comptes DE CE USER (isolation SR-001 via for_user) :
        # on ne « consomme » que les teintes que ce user voit déjà, donc le user B
        # n'est jamais contraint par les couleurs du user A. La couleur est posée
        # une fois puis figée (jamais réassignée quand d'autres comptes arrivent).
        used = [
            a.colour_hex
            for a in Account.objects.for_user(user).exclude(pk=account.pk)
            if a.colour_hex
        ]
        account.colour_hex = allocate_color(used)
        account.save(update_fields=["colour_hex"])

        builder = DETAILS_BUILDERS.get(account_type)
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

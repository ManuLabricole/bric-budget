"""
patrimoine/views/account_edit.py — édition & archivage d'un compte (#292).

Le bouton « Modifier » du panneau « Détails du compte » (page zoom) bascule la
carte en mode formulaire (HTMX), prérempli, pour éditer le compte en une fois.
Le « D » de CRUD = archivage (soft-delete), avec confirmation.

Vues :
  - account_edit_form : carte → mode formulaire prérempli (GET, HTMX)
  - account_update    : valide + persiste (POST, HTMX) → carte en lecture ou 422
  - account_archive   : soft-delete (POST, HTMX) → 204 + HX-Redirect liste

Type de compte + institution = LECTURE SEULE (changer le type muterait le
OneToOne de spécialisation, hors scope #82). On réutilise le parsing/validation
du wizard (pas de Django Forms, convention projet) et les builders du service.

Sécurité (SR-001) : compte TOUJOURS résolu via for_user → 404 pour autrui.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Account
from accounts.services import archive_account, update_account
from transactions.models import Transaction

from .account_detail import (
    _editable_fields,
    _get_account_or_404,
    back_url_for,
)
from .account_wizard import _human_validation_error, _parse_type_fields

logger = logging.getLogger(__name__)

_PANEL_TEMPLATE = "patrimoine/partials/_account_detail_panel.html"


def _decimal_str(value: Any) -> str:
    """Decimal/None → chaîne pour préremplir un input. None → vide, mais un 0
    STOCKÉ est préservé ("0") : pour pension/insurance (champs nullable), un
    contributions_ytd=0 légitime ne doit pas se vider puis revenir None au submit."""
    return "" if value is None else str(value)


def _edit_values(account: Account) -> dict[str, str]:
    """Valeurs courantes du compte → dict de préremplissage du formulaire.

    Clés alignées sur _account_form_fields.html (iban, bic, interest_rate…).
    """
    values: dict[str, str] = {
        "name": account.name,
        "currency": account.currency,
        "iban": account.iban or "",
        "contract_number": account.contract_number or "",
    }
    if account.account_type == Account.AccountType.CHECKING:
        checking = getattr(account, "checking_account", None)
        values["bic"] = checking.bic if checking else ""
    elif account.account_type == Account.AccountType.SAVINGS:
        savings = getattr(account, "savings_account", None)
        values["interest_rate"] = _decimal_str(
            savings.interest_rate if savings else None
        )
    elif account.account_type == Account.AccountType.INSURANCE:
        details = getattr(account, "life_insurance_details", None)
        for attr in ("fonds_euro_balance", "fonds_euro_rate", "management_fee_pct"):
            values[attr] = _decimal_str(getattr(details, attr, None))
    elif account.account_type in (
        Account.AccountType.PENSION_3A,
        Account.AccountType.PENSION_LP,
    ):
        details = getattr(account, "pension_details", None)
        for attr in ("annual_limit_chf", "contributions_ytd", "management_fee_pct"):
            values[attr] = _decimal_str(getattr(details, attr, None))
    return values


def _edit_context(
    account: Account,
    values: Any,
    error: str | None = None,
) -> dict[str, Any]:
    """Contexte de la carte en mode édition. `values` = _edit_values ou request.POST."""
    return {
        "account": account,
        "panel_editing": True,
        "account_type": account.account_type,
        "currencies": Account.Currency.choices,
        "chf_only": account.account_type in Account._CHF_ONLY_TYPES,
        "values": values,
        "locked_fields": [],  # rien de verrouillé en édition (≠ import #274)
        "tx_count": Transaction.objects.filter(account=account).count(),
        "error": error,
    }


def _read_context(account: Account) -> dict[str, Any]:
    """Contexte de la carte en mode lecture (re-render après update réussi)."""
    return {
        "account": account,
        "panel_editing": False,
        "editable_fields": _editable_fields(account),
    }


@login_required
def account_edit_form(request: HttpRequest, account_id: int) -> HttpResponse:
    """GET — bascule la carte Détails en mode formulaire prérempli (HTMX swap)."""
    account = _get_account_or_404(request, account_id)
    # Endpoint HTMX (swap de la carte) : navigation directe → page compte.
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:account_detail", account_id=account.pk)
    return render(
        request, _PANEL_TEMPLATE, _edit_context(account, values=_edit_values(account))
    )


@require_POST
@login_required
def account_update(request: HttpRequest, account_id: int) -> HttpResponse:
    """POST — valide + persiste l'édition. Succès : carte en lecture ; erreur : 422."""
    account = _get_account_or_404(request, account_id)
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:account_detail", account_id=account.pk)

    # Type + institution en lecture seule : on lit le type DEPUIS le compte, jamais
    # depuis le POST (un champ caché serait falsifiable).
    account_type = account.account_type
    name = request.POST.get("name", "").strip()
    contract_number = request.POST.get("contract_number", "").strip()
    currency = request.POST.get("currency", "")
    if account_type in Account._CHF_ONLY_TYPES:
        currency = Account.Currency.CHF  # devise affichée seule → on force

    error: str | None = None
    if not name:
        error = "Le nom du compte est obligatoire."
    elif len(name) > 200:
        error = "Nom trop long (200 caractères max)."
    elif len(contract_number) > 100:
        error = "N° de contrat trop long (100 caractères max)."
    elif currency not in dict(Account.Currency.choices):
        error = "Devise invalide."

    type_fields: dict[str, Any] = {}
    if error is None:
        try:
            type_fields = _parse_type_fields(request, account_type)
        except ValueError as exc:
            error = str(exc)

    if error is None:
        try:
            update_account(
                account=account,
                name=name,
                currency=currency,
                contract_number=contract_number,
                **type_fields,
            )
        except ValidationError as exc:
            error = _human_validation_error(exc)

    if error is not None:
        logger.debug(
            "account_update rejected user=%s account=%s reason=%r",
            request.user.id,
            account.pk,
            error,
        )
        return render(
            request,
            _PANEL_TEMPLATE,
            _edit_context(account, values=request.POST, error=error),
            status=422,
        )

    # Re-fetch via le helper (select_related des *Details) plutôt que refresh_from_db,
    # qui ne recharge pas les OneToOne → la carte lecture se rend sans requête en plus.
    account = _get_account_or_404(request, account_id)
    return render(request, _PANEL_TEMPLATE, _read_context(account))


@require_POST
@login_required
def account_archive(request: HttpRequest, account_id: int) -> HttpResponse:
    """POST — archive le compte (soft-delete). 204 + HX-Redirect vers la liste."""
    account = _get_account_or_404(request, account_id)
    # Endpoint HTMX (bouton de la carte) : navigation/POST direct → page compte,
    # jamais de soft-delete hors du flux HTMX (cohérent avec edit_form/update).
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:account_detail", account_id=account.pk)
    archive_account(account)
    logger.info("account_archive user=%s account=%s", request.user.id, account.pk)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = back_url_for(account)
    return response

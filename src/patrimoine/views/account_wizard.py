"""
patrimoine/views/account_wizard.py — wizard #73 : création d'une enveloppe.

Step 2 du flow « Compléter mon patrimoine » (step 1 = le picker, institutions.py) :
formulaire panel droit avec institution préremplie, champs adaptés au type via
re-render HTMX du bloc #form-dynamic. La création passe par
accounts.services.create_account (orchestration + invariants modèle).

Pas de Django Forms (convention projet) → chaque champ est casté/borné ICI.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Account, Institution
from accounts.services import create_account
from services.logos import get_institution_icon_map
from users.models import CustomUser

# Types proposés par le wizard — CARD exclu : une carte se rattache à un compte
# courant (logique transactions / compte partagé propre, future issue dédiée).
# CRYPTO visible mais SOON : connecter un exchange = clé API → niveau de
# sécurité à part (stockage chiffré, scopes lecture seule), future issue.
WIZARD_SOON_TYPES = {Account.AccountType.CRYPTO}
WIZARD_TYPE_CHOICES: list[tuple[str, str, bool]] = [
    (value, label, value in WIZARD_SOON_TYPES)
    for value, label in Account.AccountType.choices
    if value != Account.AccountType.CARD
]
# Types réellement créables (le POST refuse les SOON — un disabled se forge).
WIZARD_TYPES = {value for value, _, soon in WIZARD_TYPE_CHOICES if not soon}

# Type présélectionné selon la catégorie du catalogue — jamais bloquant : tous
# les types restent sélectionnables (Yuh est une banque ET fait du trading).
# crypto → brokerage en attendant le type crypto (SOON).
_DEFAULT_TYPE_BY_CATEGORY: dict[str, str] = {
    Institution.Category.BANK: Account.AccountType.CHECKING,
    Institution.Category.INVESTMENT: Account.AccountType.BROKERAGE,
    Institution.Category.CRYPTO: Account.AccountType.BROKERAGE,
}


def _default_type(institution: Institution) -> str:
    return _DEFAULT_TYPE_BY_CATEGORY.get(
        institution.category, Account.AccountType.CHECKING
    )


def _form_context(
    institution: Institution,
    account_type: str,
    values: QueryDict | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Contexte commun GET/erreur POST. `values` = request.POST au re-render."""
    icon_map = get_institution_icon_map()
    return {
        "institution": institution,
        "icon_url": icon_map.get(institution.icon_slug or institution.slug, ""),
        "account_type": account_type,
        "type_choices": WIZARD_TYPE_CHOICES,
        "currencies": Account.Currency.choices,
        # Le template verrouille la devise (select disabled) ; le POST la force
        # aussi côté serveur — un disabled ne soumet rien, jamais confiance au client.
        "chf_only": account_type in Account._CHF_ONLY_TYPES,
        "values": values or {},
        "error": error,
    }


def _parse_decimal(raw: str, label: str) -> Decimal | None:
    """'1 234,56' → Decimal('1234.56') (SR-002 : jamais de float). None si vide."""
    # split() avale TOUS les espaces unicode (espace fine 202F, insécable A0...)
    # que macOS/banques glissent dans les montants copiés-collés.
    cleaned = "".join(raw.split()).replace("'", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"{label} : montant invalide.") from None
    if value < 0:
        raise ValueError(f"{label} : doit être positif.")
    return value


def _human_validation_error(exc: ValidationError) -> str:
    """Messages modèle (locale en-us) → libellé UI français pour les cas connus."""
    messages = getattr(exc, "message_dict", None)
    if messages and "iban" in messages:
        return "Un compte avec cet IBAN existe déjà."
    return " ".join(exc.messages)


def _parse_type_fields(request: HttpRequest, account_type: str) -> dict[str, Any]:
    """Extrait + caste les champs propres au type. Lève ValueError si invalide."""
    post = request.POST
    if account_type == Account.AccountType.CHECKING:
        return {
            "iban": post.get("iban", "").replace(" ", "").upper(),
            "bic": post.get("bic", "").replace(" ", "").upper(),
        }
    if account_type == Account.AccountType.SAVINGS:
        return {
            "interest_rate": _parse_decimal(
                post.get("interest_rate", ""), "Taux d'intérêt"
            )
        }
    if account_type == Account.AccountType.INSURANCE:
        return {
            "fonds_euro_balance": _parse_decimal(
                post.get("fonds_euro_balance", ""), "Solde fonds euro"
            ),
            "fonds_euro_rate": _parse_decimal(
                post.get("fonds_euro_rate", ""), "Taux fonds euro"
            ),
            "management_fee_pct": _parse_decimal(
                post.get("management_fee_pct", ""), "Frais de gestion"
            ),
        }
    if account_type in (Account.AccountType.PENSION_3A, Account.AccountType.PENSION_LP):
        return {
            "annual_limit_chf": _parse_decimal(
                post.get("annual_limit_chf", ""), "Plafond annuel"
            ),
            "contributions_ytd": _parse_decimal(
                post.get("contributions_ytd", ""), "Versements"
            ),
            "management_fee_pct": _parse_decimal(
                post.get("management_fee_pct", ""), "Frais de gestion"
            ),
        }
    return {}  # investment / brokerage / crypto : aucun champ spécifique


@login_required
def account_form(request: HttpRequest) -> HttpResponse:
    """Step 2 — formulaire de création, re-rendu au changement de type (HTMX)."""
    # Endpoint HTMX (panel droit) : navigation directe → redirect, pas de partial nu.
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:overview")

    # Catalogue global (une Institution n'appartient à personne) → pas de
    # scoping user ici, même logique que le picker.
    institution = get_object_or_404(
        Institution.objects.filter(is_active=True),
        slug=request.GET.get("institution", ""),
    )
    account_type = request.GET.get("account_type", "")
    if account_type not in WIZARD_TYPES:
        account_type = _default_type(institution)

    return render(
        request,
        "patrimoine/partials/_account_form.html",
        _form_context(institution, account_type),
    )


@login_required
@require_POST
def account_create(request: HttpRequest) -> HttpResponse:
    """Création de l'enveloppe — succès : 204 + HX-Redirect bilan ; erreur : re-render."""
    if not request.headers.get("HX-Request"):
        return redirect("patrimoine:overview")

    institution = get_object_or_404(
        Institution.objects.filter(is_active=True),
        slug=request.POST.get("institution", ""),
    )
    account_type = request.POST.get("account_type", "")
    if account_type not in WIZARD_TYPES:
        # 422 = validation refusée (jamais 200 sur un POST qui n'a rien créé).
        # base.html configure htmx (responseHandling) pour swapper les 422.
        return render(
            request,
            "patrimoine/partials/_account_form.html",
            _form_context(
                institution,
                _default_type(institution),
                values=request.POST,
                error="Type de compte invalide.",
            ),
            status=422,
        )

    name = request.POST.get("name", "").strip()
    currency = request.POST.get("currency", "")
    # Identité d'import (avec l'IBAN) — commun à tous les types de comptes.
    contract_number = request.POST.get("contract_number", "").strip()
    if account_type in Account._CHF_ONLY_TYPES:
        currency = Account.Currency.CHF  # la devise est affichée seule → on force

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
            create_account(
                # @login_required garantit un user authentifié — cast pour mypy.
                user=cast(CustomUser, request.user),
                institution=institution,
                account_type=account_type,
                name=name,
                currency=currency,
                contract_number=contract_number,
                **type_fields,
            )
        except ValidationError as exc:
            # Invariants modèle (pension ⇒ CHF, IBAN dupliqué, longueurs…).
            error = _human_validation_error(exc)

    if error is not None:
        return render(
            request,
            "patrimoine/partials/_account_form.html",
            _form_context(institution, account_type, values=request.POST, error=error),
            status=422,
        )

    # Succès. Pas encore de page compte (#82) → retour bilan en full reload :
    # le compte apparaît dans sa classe d'actifs, le panel se ferme avec la page.
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("patrimoine:overview")
    return response

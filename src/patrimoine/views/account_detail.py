"""
patrimoine/views/account_detail.py — page zoom d'un compte (PR C, #82).

Le pendant « liquidités » du flow liste → zoom (cf. ui-layout.md) : la page
catégorie (asset_class) liste les comptes ; un clic mène ici.

Vues :
  - account_detail        : page (graphe mono-compte + transactions + panneau Détails)
  - set_account_period    : change la période de la courbe (POST, session)
  - account_transactions  : scroll infini page 2+ (GET, HTMX)
  - account_field_form    : passe un champ éditable en mode édition (GET, HTMX)
  - account_field_save    : valide + persiste un champ (POST, HTMX) — PAS de Django Form

Champs éditables : IBAN (Account.iban) · BIC (CheckingAccount) · Taux d'intérêt (SavingsAccount).
Le **type de compte est en lecture seule** (hors scope #82 : muter le OneToOne).

Sécurité (SR-001) : le compte est TOUJOURS résolu via Account.objects.for_user(user)
→ un id appartenant à autrui renvoie 404 (jamais une fuite). SR-002 : Decimal(str(x)).
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, InvalidPage, Paginator
from django.db import IntegrityError, transaction
from django.db.models import Min
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.iban import normalize_iban
from accounts.models import Account, BalanceSnapshot, CheckingAccount, SavingsAccount
from patrimoine.context_processors import SIDEBAR_SESSION_KEY
from patrimoine.services.asset_classes import asset_class_for_account_type
from patrimoine.services.balance_history import PERIODS, period_bounds
from patrimoine.services.chart_data import single_account_series
from patrimoine.services.valuation import current_value
from patrimoine.views.overview import PERIOD_LABELS
from services.logos import get_institution_icon_map
from transactions.models import Transaction

logger = logging.getLogger(__name__)

_PERIOD_KEY_PREFIX = "patrimoine_account_period_"
DEFAULT_PERIOD = "1m"
TX_PAGE_SIZE = 50

# Cible HTMX du swap (graphe + sélecteurs re-rendus sans recharger la page).
_BODY_TARGET = "#account-detail-body"

# Champs éditables inline par type de compte (str, car account_type est un str en DB).
# checking : iban/bic ; savings : iban/taux. L'IBAN vit sur Account et rattache les
# imports UBS (universel checking + savings, cf. resolver) → éditable pour les deux.
# Tout autre champ = refusé.
_EDITABLE_FIELDS: dict[str, tuple[str, ...]] = {
    Account.AccountType.CHECKING: ("iban", "bic"),
    Account.AccountType.SAVINGS: ("iban", "interest_rate"),
}

# Forme minimale d'un IBAN : 2 lettres pays + 2 chiffres de contrôle + 11..30
# alphanumériques (15..34 au total). On NE valide PAS la clé mod-97 (hors scope) —
# même politique que le wizard, qui se repose sur l'unicité DB.
_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
# BIC/SWIFT : 8 ou 11 caractères (banque + pays + localité [+ branche]).
_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def _period_key(account_id: int) -> str:
    return f"{_PERIOD_KEY_PREFIX}{account_id}"


def _get_account_or_404(request: HttpRequest, account_id: int) -> Account:
    """Compte de l'utilisateur (SR-001) ou 404 — jamais .get() nu sur l'id."""
    try:
        account = (
            Account.objects.for_user(request.user)
            .filter(is_active=True)
            # OneToOne *Details lues par _editable_fields / _edit_values (#292) :
            # select_related évite une requête par sous-modèle au rendu de la carte.
            .select_related(
                "institution",
                "checking_account",
                "savings_account",
                "life_insurance_details",
                "pension_details",
            )
            .get(pk=account_id)
        )
    except Account.DoesNotExist:
        raise Http404("Compte introuvable.") from None
    return cast("Account", account)


def _earliest_date(account: Account):
    snap = BalanceSnapshot.objects.filter(account=account).aggregate(m=Min("date"))["m"]
    tx = Transaction.objects.filter(account=account).aggregate(m=Min("date"))["m"]
    candidates = [d for d in (snap, tx) if d is not None]
    return min(candidates) if candidates else None


def _get_tx_page(account: Account, page_number: int):
    """Queryset paginé des transactions du compte (icône institution résolue)."""
    qs = (
        Transaction.objects.filter(account=account)
        .select_related("account", "account__institution", "category", "subcategory")
        .order_by("-date", "-id")
    )
    paginator = Paginator(qs, TX_PAGE_SIZE)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    except InvalidPage:
        page_obj = paginator.page(1)

    icon_map = get_institution_icon_map()
    tx_list = list(page_obj.object_list)
    inst = account.institution
    icon_url = icon_map.get(inst.icon_slug, "") if inst else ""
    for tx in tx_list:
        tx.institution_icon_url = icon_url
    return tx_list, page_obj


def _editable_fields(account: Account) -> list[dict]:
    """Lignes du panneau Détails éditable selon le type (IBAN/BIC ou Taux)."""
    fields: list[dict] = []
    if account.account_type == Account.AccountType.CHECKING:
        checking = getattr(account, "checking_account", None)
        fields.append(
            {
                "name": "iban",
                "label": "IBAN",
                # IBAN canonique = Account.iban (source unique, consolidation #82).
                "value": account.iban,
                "kind": "text",
            }
        )
        fields.append(
            {
                "name": "bic",
                "label": "BIC / SWIFT",
                "value": (checking.bic or None) if checking else None,
                "kind": "text",
            }
        )
    elif account.account_type == Account.AccountType.SAVINGS:
        fields.append(
            {
                "name": "iban",
                "label": "IBAN",
                # IBAN canonique = Account.iban (source unique, consolidation #82).
                "value": account.iban,
                "kind": "text",
            }
        )
        savings = getattr(account, "savings_account", None)
        # 0 (ou None) → considéré « non renseigné » côté UI (affiché « — »).
        rate = savings.interest_rate if savings else None
        fields.append(
            {
                "name": "interest_rate",
                "label": "Taux d'intérêt",
                "value": rate if rate else None,
                "suffix": "%",
                "kind": "rate",
            }
        )
    return fields


def back_url_for(account: Account) -> str:
    """Lien retour : page catégorie du compte si sa classe est fonctionnelle, sinon bilan.

    Partagé par la page détail et l'archivage (#292) qui y redirige après soft-delete.
    """
    asset_class = asset_class_for_account_type(account.account_type)
    if asset_class is not None and asset_class.functional:
        return reverse("patrimoine:asset_class", args=[asset_class.slug])
    return reverse("patrimoine:overview")


def _detail_context(request: HttpRequest, account: Account) -> dict:
    period = request.session.get(_period_key(account.pk), DEFAULT_PERIOD)
    if period not in PERIODS:
        period = DEFAULT_PERIOD

    today = timezone.localdate()
    start, end = period_bounds(
        period, today=today, earliest=_earliest_date(account) or today
    )
    chart_json = single_account_series(account, start, end)

    back_url = back_url_for(account)

    txs, page_obj = _get_tx_page(account, 1)

    return {
        "account": account,
        "back_url": back_url,
        "current_value": current_value(account, today),
        "chart_json": chart_json,
        "period": period,
        "period_choices": [(k, PERIOD_LABELS[k]) for k in PERIODS],
        "htmx_target": _BODY_TARGET,
        "editable_fields": _editable_fields(account),
        "txs": txs,
        "page_obj": page_obj,
        "account_tx_url": reverse("patrimoine:account_transactions", args=[account.pk]),
    }


@login_required
def account_detail(request: HttpRequest, account_id: int) -> HttpResponse:
    """Page zoom d'un compte. 404 si l'id n'appartient pas à l'utilisateur (SR-001)."""
    account = _get_account_or_404(request, account_id)
    # Atterrir sur une page compte garde la section patrimoine dépliée dans la sidebar.
    request.session[SIDEBAR_SESSION_KEY] = True
    return render(
        request, "patrimoine/account_detail.html", _detail_context(request, account)
    )


@require_POST
@login_required
def set_account_period(
    request: HttpRequest, account_id: int, period: str
) -> HttpResponse:
    """Change la période de la courbe (session). HTMX → swap corps ; sinon redirect."""
    account = _get_account_or_404(request, account_id)
    if period in PERIODS:
        request.session[_period_key(account.pk)] = period
        logger.debug(
            "account_set_period user=%s account=%s period=%s",
            request.user.id,
            account.pk,
            period,
        )
    else:
        logger.debug(
            "account_set_period rejected user=%s account=%s period=%r",
            request.user.id,
            account.pk,
            period,
        )
    if request.headers.get("HX-Request"):
        return render(
            request,
            "patrimoine/partials/_account_detail_body.html",
            _detail_context(request, account),
        )
    return redirect("patrimoine:account_detail", account_id=account.pk)


@login_required
def account_transactions(request: HttpRequest, account_id: int) -> HttpResponse:
    """Scroll infini page 2+ — nouvelles lignes + sentinel (page 1 rendue par la page)."""
    account = _get_account_or_404(request, account_id)
    try:
        page_number = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page_number = 1

    txs, page_obj = _get_tx_page(account, page_number)
    return render(
        request,
        "patrimoine/partials/_account_detail_tx_rows.html",
        {
            "account": account,
            "txs": txs,
            "page_obj": page_obj,
            "account_tx_url": reverse(
                "patrimoine:account_transactions", args=[account.pk]
            ),
        },
    )


# =============================================================================
# Édition inline (panneau Détails) — validation DANS la vue, pas de Django Form.
# =============================================================================


def _field_meta(account: Account, field: str) -> dict | None:
    """Retrouve la ligne `_editable_fields` correspondant à `field` (ou None)."""
    for meta in _editable_fields(account):
        if meta["name"] == field:
            return meta
    return None


def _render_field(
    request: HttpRequest,
    account: Account,
    field: str,
    *,
    editing: bool,
    error: str | None = None,
    raw_value: str | None = None,
) -> HttpResponse:
    """Re-rend une ligne du panneau Détails (lecture ou édition)."""
    meta = _field_meta(account, field)
    if meta is None:  # pragma: no cover — garde défensive (URL forgée filtrée en amont)
        raise Http404("Champ non éditable.")
    ctx = {
        "account": account,
        "field": meta,
        "editing": editing,
        "error": error,
        # En erreur, on réaffiche ce que l'utilisateur a tapé, pas la valeur DB.
        "raw_value": raw_value,
    }
    status = 422 if error else 200
    return render(
        request, "patrimoine/partials/_account_detail_field.html", ctx, status=status
    )


@login_required
def account_field_form(
    request: HttpRequest, account_id: int, field: str
) -> HttpResponse:
    """GET — passe une ligne du panneau Détails en mode édition (HTMX swap)."""
    account = _get_account_or_404(request, account_id)
    if field not in _EDITABLE_FIELDS.get(account.account_type, ()):
        # Champ non éditable pour ce type (URL forgée) → 404, pas de formulaire.
        raise Http404("Champ non éditable pour ce type de compte.")
    return _render_field(request, account, field, editing=True)


def _validate_iban(raw: str) -> tuple[str | None, str | None]:
    """('CH56…'|None, error|None). Normalise (maj, sans blanc). Vide → (None, None)."""
    value = normalize_iban(raw)
    if not value:
        return None, None  # IBAN effacé → None (autorisé, NULL != NULL)
    if not _IBAN_RE.match(value):
        return (
            None,
            "IBAN invalide (format attendu : 2 lettres, 2 chiffres, puis 11 à 30 caractères).",
        )
    return value, None


def _validate_bic(raw: str) -> tuple[str | None, str | None]:
    """(bic|None, error|None). Normalise (maj, sans espaces). Vide → ('', None)."""
    value = raw.replace(" ", "").upper()
    if not value:
        return "", None  # BIC optionnel → vide autorisé
    if not _BIC_RE.match(value):
        return None, "BIC invalide (8 ou 11 caractères, ex. BCVLCH2L)."
    return value, None


def _validate_rate(raw: str) -> tuple[Decimal | None, str | None]:
    """(Decimal|None, error|None). '1,5' → Decimal('1.5'). SR-002 : jamais Decimal(float)."""
    cleaned = "".join(raw.split()).replace("'", "").replace(",", ".")
    if not cleaned:
        return Decimal("0"), None  # taux effacé → 0 (NOT NULL, default=0)
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None, "Taux invalide."
    if value < 0:
        return None, "Le taux doit être positif."
    # max_digits=5, decimal_places=2 → partie entière ≤ 3 chiffres (≤ 999.99 %).
    if value > Decimal("999.99"):
        return None, "Taux trop élevé."
    return value, None


@require_POST
@login_required
def account_field_save(
    request: HttpRequest, account_id: int, field: str
) -> HttpResponse:
    """POST — valide + persiste un champ éditable, re-rend la ligne en lecture."""
    account = _get_account_or_404(request, account_id)
    if field not in _EDITABLE_FIELDS.get(account.account_type, ()):
        raise Http404("Champ non éditable pour ce type de compte.")

    raw = request.POST.get("value", "")

    # Une variable typée par branche (mypy) : iban/bic → str|None, taux → Decimal.
    if field == "iban":
        iban_value, error = _validate_iban(raw)
        # Invariant d'identité (même règle que create/update_account) : un compte ne
        # peut pas se retrouver SANS IBAN ET SANS n° de contrat, sinon plus aucun
        # import ne peut le rattacher. Le modèle ne l'enforce pas (Account.clean ne
        # couvre que CHF-only) → on garde-fou ici, sinon le crayon inline permettrait
        # d'orpheliner un compte (le formulaire panel, lui, le bloque déjà).
        if (
            error is None
            and iban_value is None
            and not (account.contract_number or "").strip()
        ):
            error = (
                "Renseigne l'IBAN ou le n° de contrat — c'est ce qui rattache "
                "les imports de relevés à ce compte."
            )
        if error is None:
            error = _save_iban(account, iban_value)
    elif field == "bic":
        bic_value, error = _validate_bic(raw)
        if error is None and bic_value is not None:
            _save_checking_field(account, "bic", bic_value)
    elif field == "interest_rate":
        rate_value, error = _validate_rate(raw)
        if error is None and rate_value is not None:
            _save_savings_rate(account, rate_value)
    else:  # pragma: no cover — filtré par _EDITABLE_FIELDS
        raise Http404("Champ non éditable.")

    if error is not None:
        logger.debug(
            "account_field_save rejected user=%s account=%s field=%s reason=%r",
            request.user.id,
            account.pk,
            field,
            error,
        )
        return _render_field(
            request, account, field, editing=True, error=error, raw_value=raw
        )

    logger.info(
        "account_field_save ok user=%s account=%s field=%s",
        request.user.id,
        account.pk,
        field,
    )
    account.refresh_from_db()
    return _render_field(request, account, field, editing=False)


def _save_iban(account: Account, value: str | None) -> str | None:
    """
    Persiste l'IBAN sur Account UNIQUEMENT (source de vérité canonique, #82).

    Retourne un message d'erreur si l'IBAN est déjà pris par un autre compte
    (unique=True sur Account.iban), sinon None. Atomique.
    """
    try:
        with transaction.atomic():
            account.iban = value
            # full_clean() lève ValidationError sur collision unique AVANT le save.
            account.full_clean()
            account.save(update_fields=["iban"])
    except (ValidationError, IntegrityError):
        return "Un compte avec cet IBAN existe déjà."
    return None


def _save_checking_field(account: Account, attr: str, value) -> None:
    """Persiste un champ simple de CheckingAccount (BIC) — crée la ligne si absente."""
    checking, _ = CheckingAccount.objects.get_or_create(account=account)
    setattr(checking, attr, value)
    checking.full_clean()
    checking.save(update_fields=[attr])


def _save_savings_rate(account: Account, value: Decimal) -> None:
    """Persiste le taux d'intérêt de SavingsAccount — crée la ligne si absente."""
    savings, _ = SavingsAccount.objects.get_or_create(account=account)
    savings.interest_rate = value
    savings.full_clean()
    savings.save(update_fields=["interest_rate"])

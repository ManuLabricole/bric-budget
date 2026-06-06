"""
patrimoine/views/asset_class.py — page d'une classe d'actifs fonctionnelle.

Vues :
  - asset_class_page          : page principale (graphe + tabs comptes/transactions)
  - set_asset_class_period    : change la période de la courbe (POST, session)
  - set_asset_class_stacked   : bascule mode standard/empilé (POST, session)
  - set_asset_class_tab       : bascule onglet Comptes/Transactions (GET, session)
  - asset_class_transactions  : scroll infini page 2+ (GET, HTMX)

Sécurité (SR-001) : listing scopé via Account.objects.for_user — jamais .all() nu.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, InvalidPage, Paginator
from django.db.models import Min
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Account, BalanceSnapshot
from budget.utils import _resolve_bank_icon_map
from patrimoine.context_processors import SIDEBAR_SESSION_KEY
from patrimoine.services.asset_classes import get_asset_class
from patrimoine.services.balance_history import PERIODS, period_bounds
from patrimoine.services.bilan import BilanNode
from patrimoine.services.chart_data import (
    _STACK_PALETTE,
    account_class_series,
    distribution,
)
from patrimoine.services.valuation import current_value
from patrimoine.views.overview import PERIOD_LABELS
from transactions.models import Transaction

_PERIOD_KEY_PREFIX = "patrimoine_ac_period_"
_STACKED_KEY_PREFIX = "patrimoine_ac_stacked_"
_TAB_KEY_PREFIX = "patrimoine_ac_tab_"
_VALID_TABS = ("comptes", "transactions")
DEFAULT_PERIOD = "1m"
TX_PAGE_SIZE = 50

# Cible HTMX du swap (graphe + liste re-rendu sans recharger la page).
_BODY_TARGET = "#asset-class-body"


def _period_key(slug: str) -> str:
    return f"{_PERIOD_KEY_PREFIX}{slug}"


def _stacked_key(slug: str) -> str:
    return f"{_STACKED_KEY_PREFIX}{slug}"


def _tab_key(slug: str) -> str:
    return f"{_TAB_KEY_PREFIX}{slug}"


def _get_or_404(slug: str):
    """Résout une AssetClass ou lève Http404."""
    asset_class = get_asset_class(slug)
    if asset_class is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")
    return asset_class


def _get_accounts(user, asset_class) -> list:
    """Comptes actifs de l'utilisateur pour cette classe (SR-001)."""
    return list(
        Account.objects.for_user(user)
        .filter(is_active=True, account_type__in=asset_class.account_types)
        .select_related("institution")
        .order_by("institution__name", "name")
    )


def _earliest_date(accounts) -> datetime.date | None:
    if not accounts:
        return None
    ids = [a.id for a in accounts]
    snap = BalanceSnapshot.objects.filter(account_id__in=ids).aggregate(m=Min("date"))[
        "m"
    ]
    tx = Transaction.objects.filter(account_id__in=ids).aggregate(m=Min("date"))["m"]
    candidates = [d for d in (snap, tx) if d is not None]
    return min(candidates) if candidates else None


def _build_institution_groups(accounts, values: dict) -> list[dict]:
    """
    Groupe les comptes par institution avec valeurs courantes en CHF.

    Retourne [{institution, accounts: [{account, value}], total}].
    `values` = {account.pk: Decimal | None} pré-calculé par l'appelant (évite N+1).
    `total` = somme des valeurs non-None (0 si aucune).
    """
    groups: dict[int | None, dict] = {}
    for acc in accounts:
        inst = acc.institution
        key = inst.id if inst is not None else None
        if key not in groups:
            groups[key] = {
                "institution": inst,
                "accounts": [],
                "total": Decimal("0"),
            }
        val = values.get(acc.pk)
        groups[key]["accounts"].append({"account": acc, "value": val})
        if val is not None:
            groups[key]["total"] += val
    return list(groups.values())


def _get_tx_page(accounts, page_number: int):
    """Queryset paginé des transactions pour les comptes de la classe."""
    account_ids = [a.id for a in accounts]
    qs = (
        Transaction.objects.filter(account_id__in=account_ids)
        .select_related("account", "account__institution", "category", "subcategory")
        .order_by("-date", "-id")
    )
    paginator = Paginator(qs, TX_PAGE_SIZE)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        # Page hors-borne → dernière page (has_next=False, sentinel disparu, scroll terminé).
        page_obj = paginator.page(paginator.num_pages)
    except InvalidPage:
        page_obj = paginator.page(1)

    bank_icon_map = _resolve_bank_icon_map()
    tx_list = list(page_obj.object_list)
    for tx in tx_list:
        slug = (
            tx.account.institution.icon_slug
            if tx.account and tx.account.institution
            else ""
        )
        tx.bank_icon_url = bank_icon_map.get(slug, "")

    return tx_list, page_obj


def _asset_class_context(request, asset_class) -> dict:
    accounts = _get_accounts(request.user, asset_class)
    period = request.session.get(_period_key(asset_class.slug), DEFAULT_PERIOD)
    if period not in PERIODS:
        period = DEFAULT_PERIOD
    stacked = request.session.get(_stacked_key(asset_class.slug), True)
    tab = request.session.get(_tab_key(asset_class.slug), "comptes")
    if tab not in _VALID_TABS:
        tab = "comptes"

    today = timezone.localdate()
    # Valorisation courante calculée une seule fois — partagée par institution_groups et dist.
    values_today = {acc.pk: current_value(acc, today) for acc in accounts}

    start, end = period_bounds(
        period, today=today, earliest=_earliest_date(accounts) or today
    )

    chart_json = account_class_series(accounts, start, end)

    # Distribution treemap : couleurs alignées avec les séries du graphe (_STACK_PALETTE).
    dist_nodes = [
        BilanNode(
            label=acc.name,
            value=values_today.get(acc.pk),
            color=_STACK_PALETTE[i % len(_STACK_PALETTE)],
            url=None,
        )
        for i, acc in enumerate(accounts)
    ]
    dist_json = distribution([n for n in dist_nodes if n.value is not None])

    ctx: dict = {
        "asset_class": asset_class,
        "institution_groups": _build_institution_groups(accounts, values_today),
        "chart_json": chart_json,
        "dist_json": dist_json,
        "stacked": stacked,
        "period": period,
        "period_choices": [(k, PERIOD_LABELS[k]) for k in PERIODS],
        "htmx_target": _BODY_TARGET,
        "tab": tab,
    }

    # Transactions chargées uniquement quand l'onglet est actif (perf).
    if tab == "transactions":
        txs, page_obj = _get_tx_page(accounts, 1)
        ctx["txs"] = txs
        ctx["page_obj"] = page_obj
        ctx["asset_class_tx_url"] = reverse(
            "patrimoine:asset_class_transactions", args=[asset_class.slug]
        )

    return ctx


def _body_or_redirect(request, asset_class):
    """HTMX → re-rend le partial du corps ; sinon redirect PRG."""
    if request.headers.get("HX-Request"):
        return render(
            request,
            "patrimoine/partials/_asset_class_body.html",
            _asset_class_context(request, asset_class),
        )
    return redirect("patrimoine:asset_class", slug=asset_class.slug)


@login_required
def asset_class_page(request, slug: str):
    """Page d'une classe d'actifs. 404 si slug inconnu ; état SOON si non fonctionnelle."""
    asset_class = _get_or_404(slug)

    # Atterrir sur une page classe d'actifs force le dépliement de la section sidebar.
    request.session[SIDEBAR_SESSION_KEY] = True

    if not asset_class.functional:
        return render(
            request,
            "patrimoine/asset_class_soon.html",
            {"asset_class": asset_class},
        )

    return render(
        request,
        "patrimoine/asset_class.html",
        _asset_class_context(request, asset_class),
    )


@require_POST
@login_required
def set_asset_class_period(request, slug: str, period: str):
    """Change la période de la courbe (session). HTMX → swap corps ; sinon redirect."""
    asset_class = _get_or_404(slug)
    if period in PERIODS:
        request.session[_period_key(slug)] = period
    return _body_or_redirect(request, asset_class)


@require_POST
@login_required
def set_asset_class_stacked(request, slug: str):
    """Bascule mode standard/empilé (session). HTMX → swap corps ; sinon redirect."""
    asset_class = _get_or_404(slug)
    request.session[_stacked_key(slug)] = request.POST.get("stacked") == "1"
    return _body_or_redirect(request, asset_class)


@login_required
def set_asset_class_tab(request, slug: str, tab: str):
    """Bascule l'onglet Comptes/Transactions (GET → session → redirect)."""
    _get_or_404(slug)
    if tab in _VALID_TABS:
        request.session[_tab_key(slug)] = tab
    return redirect("patrimoine:asset_class", slug=slug)


@login_required
def asset_class_transactions(request, slug: str):
    """
    Scroll infini page 2+ — retourne uniquement les nouvelles lignes + sentinel.

    Page 1 est rendue directement par asset_class_page (dans le contexte initial).
    Ce endpoint est appelé par le sentinel HTMX quand l'utilisateur scrolle.
    """
    asset_class = _get_or_404(slug)
    accounts = _get_accounts(request.user, asset_class)
    try:
        page_number = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page_number = 1

    txs, page_obj = _get_tx_page(accounts, page_number)

    return render(
        request,
        "patrimoine/partials/_asset_class_tx_rows.html",
        {
            "asset_class": asset_class,
            "txs": txs,
            "page_obj": page_obj,
            "asset_class_tx_url": reverse(
                "patrimoine:asset_class_transactions", args=[slug]
            ),
        },
    )

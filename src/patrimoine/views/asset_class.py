"""
patrimoine/views/asset_class.py — page d'une classe d'actifs fonctionnelle.

Vue principale + endpoints HTMX :
  - set_asset_class_period  : change la période de la courbe (POST, session)
  - set_asset_class_stacked : bascule mode standard/empilé (POST, session)

Sécurité (SR-001) : listing scopé via Account.objects.for_user — jamais .all() nu.
"""

from __future__ import annotations

import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Min
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Account, BalanceSnapshot
from patrimoine.context_processors import SIDEBAR_SESSION_KEY
from patrimoine.services.asset_classes import get_asset_class
from patrimoine.services.balance_history import PERIODS, period_bounds
from patrimoine.services.bilan import BilanNode
from patrimoine.services.chart_data import account_class_series, distribution
from patrimoine.services.valuation import current_value
from patrimoine.views.overview import PERIOD_LABELS
from transactions.models import Transaction

_PERIOD_KEY_PREFIX = "patrimoine_ac_period_"
_STACKED_KEY_PREFIX = "patrimoine_ac_stacked_"
DEFAULT_PERIOD = "1m"

# Cible HTMX du swap (graphe + liste re-rendu sans recharger la page).
_BODY_TARGET = "#asset-class-body"


def _period_key(slug: str) -> str:
    return f"{_PERIOD_KEY_PREFIX}{slug}"


def _stacked_key(slug: str) -> str:
    return f"{_STACKED_KEY_PREFIX}{slug}"


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


def _group_by_institution(accounts) -> list[dict]:
    """[{institution, accounts: [...]}] pour le listing avec chevron par institution."""
    groups: dict[int, dict] = {}
    for acc in accounts:
        inst = acc.institution
        if inst.id not in groups:
            groups[inst.id] = {"institution": inst, "accounts": []}
        groups[inst.id]["accounts"].append(acc)
    return list(groups.values())


def _asset_class_context(request, asset_class) -> dict:
    accounts = _get_accounts(request.user, asset_class)
    period = request.session.get(_period_key(asset_class.slug), DEFAULT_PERIOD)
    if period not in PERIODS:
        period = DEFAULT_PERIOD
    stacked = request.session.get(_stacked_key(asset_class.slug), True)

    today = timezone.localdate()
    start, end = period_bounds(
        period, today=today, earliest=_earliest_date(accounts) or today
    )

    chart_json = account_class_series(accounts, start, end)

    # Distribution par compte : valeur courante CHF, couleur de la classe.
    dist_nodes = [
        BilanNode(
            label=acc.name,
            value=current_value(acc, today),
            color=asset_class.color,
            url=None,
        )
        for acc in accounts
    ]
    dist_json = distribution([n for n in dist_nodes if n.value is not None])

    return {
        "asset_class": asset_class,
        "institution_groups": _group_by_institution(accounts),
        "chart_json": chart_json,
        "dist_json": dist_json,
        "stacked": stacked,
        "period": period,
        "period_choices": [(k, PERIOD_LABELS[k]) for k in PERIODS],
        "htmx_target": _BODY_TARGET,
    }


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
    asset_class = get_asset_class(slug)
    if asset_class is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")

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
    asset_class = get_asset_class(slug)
    if asset_class is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")
    if period in PERIODS:
        request.session[_period_key(slug)] = period
    return _body_or_redirect(request, asset_class)


@require_POST
@login_required
def set_asset_class_stacked(request, slug: str):
    """Bascule mode standard/empilé (session). HTMX → swap corps ; sinon redirect."""
    asset_class = get_asset_class(slug)
    if asset_class is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")
    request.session[_stacked_key(slug)] = request.POST.get("stacked") == "1"
    return _body_or_redirect(request, asset_class)

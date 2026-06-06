"""
patrimoine/views/overview.py — page bilan « Patrimoine brut » (overview).

Vue FINE : scope les comptes (for_user / SR-001), lit la période en session, appelle les
services (bilan + chart_data) et rend. Aucun calcul ici — tout est dans services/.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Min
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Account, BalanceSnapshot
from patrimoine.context_processors import SIDEBAR_SESSION_KEY
from patrimoine.services.asset_classes import ASSET_CLASSES, get_asset_class
from patrimoine.services.balance_history import PERIODS, period_bounds
from patrimoine.services.bilan import overview_bilan
from patrimoine.services.chart_data import chart_series, distribution
from patrimoine.views.filters import (
    FILTER_SESSION_KEY,
    _all_slugs,
    selected_class_slugs,
)
from transactions.models import Transaction

# Clé de session de la période sélectionnée + libellés d'affichage des pills.
PERIOD_SESSION_KEY = "patrimoine_period"
DEFAULT_PERIOD = "1m"
PERIOD_LABELS = {
    "1j": "1J",
    "7j": "7J",
    "1m": "1M",
    "3m": "3M",
    "ytd": "YTD",
    "1a": "1A",
    "tout": "TOUT",
}


def _user_accounts(user) -> list:
    """Comptes actifs de l'utilisateur (SR-001 : scoping for_user)."""
    return list(
        Account.objects.for_user(user)
        .filter(is_active=True)
        .select_related("institution")
    )


def _earliest_date(accounts) -> datetime.date | None:
    """Date la plus ancienne connue (snapshot ou transaction) pour borner 'tout'."""
    if not accounts:
        return None
    ids = [a.id for a in accounts]
    snap = BalanceSnapshot.objects.filter(account_id__in=ids).aggregate(m=Min("date"))[
        "m"
    ]
    tx = Transaction.objects.filter(account_id__in=ids).aggregate(m=Min("date"))["m"]
    candidates = [d for d in (snap, tx) if d is not None]
    return min(candidates) if candidates else None


# Cible HTMX du swap (le bloc bilan re-rendu sans recharger la page).
OVERVIEW_BODY_TARGET = "#overview-body"


def _overview_context(request, *, filter_open: bool = False) -> dict:
    """Contexte du bilan overview — partagé entre la page pleine et les swaps HTMX."""
    accounts = _user_accounts(request.user)
    period = request.session.get(PERIOD_SESSION_KEY, DEFAULT_PERIOD)
    if period not in PERIODS:
        period = DEFAULT_PERIOD

    today = timezone.localdate()
    start, end = period_bounds(
        period, today=today, earliest=_earliest_date(accounts) or today
    )

    selected = set(selected_class_slugs(request.session))
    nodes = overview_bilan(accounts, on=today, selected_slugs=selected)
    total = sum((n.value for n in nodes if n.value is not None), Decimal("0"))

    return {
        "nodes": nodes,
        "total_value": total,
        "chart_json": chart_series(accounts, start, end, selected_slugs=selected),
        "dist_json": distribution(nodes),
        "period": period,
        "period_choices": [(k, PERIOD_LABELS[k]) for k in PERIODS],
        "class_filter_items": [
            {
                "key": ac.slug,
                "label": ac.label,
                "color": ac.color,
                "selected": ac.slug in selected,
            }
            for ac in ASSET_CLASSES
        ],
        "class_filter_n_selected": len(selected),
        "class_filter_n_total": len(ASSET_CLASSES),
        # Câblage HTMX : les sélecteurs swappent ce bloc au lieu de recharger la page.
        "htmx_target": OVERVIEW_BODY_TARGET,
        "class_filter_open": filter_open,
        "today": today,
    }


def _body_or_redirect(request, *, filter_open: bool = False):
    """Requête HTMX → re-rend le bloc bilan (pas de reload) ; sinon redirect (PRG fallback)."""
    if request.headers.get("HX-Request"):
        return render(
            request,
            "patrimoine/partials/_overview_body.html",
            _overview_context(request, filter_open=filter_open),
        )
    return redirect("patrimoine:overview")


@login_required
def overview(request):
    """Bilan consolidé : courbe net worth + table actifs + donut. Performance = placeholder SOON."""
    request.session[SIDEBAR_SESSION_KEY] = True
    return render(request, "patrimoine/overview.html", _overview_context(request))


@require_POST
@login_required
def set_period(request, period: str):
    """Change la période (session). HTMX → swap du bloc bilan ; sinon redirect."""
    if period in PERIODS:
        request.session[PERIOD_SESSION_KEY] = period
    return _body_or_redirect(request)


@require_POST
@login_required
def toggle_class(request, slug: str):
    """Coche/décoche une classe d'actifs. HTMX → swap (dropdown gardé ouvert) ; sinon redirect."""
    if slug == "all":
        request.session[FILTER_SESSION_KEY] = _all_slugs()
        return _body_or_redirect(request, filter_open=True)
    if get_asset_class(slug) is None:
        raise Http404(f"Classe d'actifs inconnue : {slug}")
    selected = set(selected_class_slugs(request.session))
    selected.discard(slug) if slug in selected else selected.add(slug)
    request.session[FILTER_SESSION_KEY] = [s for s in _all_slugs() if s in selected]
    return _body_or_redirect(request, filter_open=True)

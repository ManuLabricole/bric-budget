"""
patrimoine/services/balance_history.py — moteur d'ancrage du solde dans le temps.

Problème
--------
Les `BalanceSnapshot` sont rares (créés aux imports). Un recalcul pur du solde
depuis les transactions dérive (transaction manquante, frais prélevés en silence).

Solution : ancrage hybride
--------------------------
- Les snapshots sont des **ancres** (vérité banque) via `authoritative_balance`.
- Entre deux ancres, on **marche** les transactions pour dessiner la courbe.
- À chaque snapshot, on **re-cale** sur la valeur banque → la dérive ne s'accumule
  jamais d'un import à l'autre (elle reste bornée à l'écart entre deux snapshots).

Convention de signe : `Transaction.amount` négatif = débit, positif = crédit.
Donc  solde(jour) = solde(ancre) + Σ amount des tx postérieures à l'ancre.

Précision : tout en `Decimal` (SR-002) — jamais de float.
"""

from __future__ import annotations

import calendar
import datetime
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from django.utils import timezone

# Clés de période (alignées sur les boutons UI 1J/7J/1M/3M/YTD/1A/TOUT et la session).
PERIODS = ("1j", "7j", "1m", "3m", "ytd", "1a", "tout")


@dataclass
class BalanceSeries:
    """Série journalière de solde. `anchored=False` si aucun snapshot n'ancre la série."""

    dates: list[datetime.date]
    values: list[Decimal]
    anchored: bool
    # False = au moins une ancre nécessaire est manquante (ex. balance_chf NULL :
    # conversion CHF pas encore calculée). On remplace alors la valeur par 0 pour le
    # tracé MAIS on signale l'incomplétude — jamais de 0 silencieux pris pour une vérité.
    complete: bool = True


def period_bounds(
    period: str,
    today: datetime.date | None = None,
    *,
    earliest: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    """
    Retourne (start, end) pour une clé de période. `earliest` borne 'tout'.

    'tout' sans `earliest` → start = today (série d'un seul jour) : sans plus ancienne
    transaction connue, on ne peut pas remonter plus loin.
    """
    if today is None:
        today = timezone.localdate()  # date locale (USE_TZ) — pas date.today() naïf
    end = today
    if period == "1j":
        start = today - datetime.timedelta(days=1)
    elif period == "7j":
        start = today - datetime.timedelta(days=7)
    elif period == "1m":
        start = _subtract_months(today, 1)
    elif period == "3m":
        start = _subtract_months(today, 3)
    elif period == "ytd":
        start = datetime.date(today.year, 1, 1)
    elif period == "1a":
        start = _subtract_months(today, 12)
    elif period == "tout":
        start = earliest if earliest is not None else today
    else:
        raise ValueError(f"Unknown period: {period!r}")
    return start, end


def account_balance_series(
    account,
    start: datetime.date,
    end: datetime.date,
    *,
    in_chf: bool = False,
) -> BalanceSeries:
    """
    Série journalière du solde d'un compte entre start et end (inclus).

    ⚠️ Sécurité (SR-001) : `account` DOIT déjà être scopé utilisateur par l'appelant
    (`Account.objects.for_user(request.user)`). Ce service ne vérifie pas l'appartenance
    et lit BalanceSnapshot/Transaction par `account=account` — passer un compte non scopé
    = IDOR. Au branchement d'une vue (PR B/C) : récupérer le compte via for_user + test IDOR.
    """
    from accounts.models import BalanceSnapshot

    snapshots = list(BalanceSnapshot.objects.filter(account=account).order_by("date"))
    snap_dates = [s.date for s in snapshots]
    sorted_tx_dates, cumsums = _build_tx_cumsums(account, in_chf)

    dates: list[datetime.date] = []
    raw: list[Decimal | None] = []
    current = start
    one_day = datetime.timedelta(days=1)
    while current <= end:
        dates.append(current)
        raw.append(
            _day_balance(
                current, snap_dates, snapshots, sorted_tx_dates, cumsums, in_chf
            )
        )
        current += one_day

    # None = ancre indisponible → on signale complete=False et on trace 0 (jamais
    # un 0 silencieux pris pour une vérité). complete reste True si aucun None.
    complete = all(v is not None for v in raw)
    values = [v if v is not None else Decimal("0") for v in raw]
    return BalanceSeries(
        dates=dates, values=values, anchored=bool(snapshots), complete=complete
    )


def consolidated_balance_series(
    accounts,
    start: datetime.date,
    end: datetime.date,
) -> BalanceSeries:
    """
    Somme en CHF des séries de plusieurs comptes (net worth d'une catégorie).

    ⚠️ Sécurité (SR-001) : `accounts` DOIT déjà être un queryset scopé `for_user` — cf.
    `account_balance_series`. Aucune vérification d'appartenance ici.
    """
    accounts = list(accounts)
    if not accounts:
        n = (end - start).days + 1
        current = start
        dates: list[datetime.date] = []
        while current <= end:
            dates.append(current)
            current += datetime.timedelta(days=1)
        return BalanceSeries(dates=dates, values=[Decimal("0")] * n, anchored=False)

    series = [account_balance_series(acc, start, end, in_chf=True) for acc in accounts]
    dates = series[0].dates
    values = [
        sum((s.values[i] for s in series), Decimal("0")) for i in range(len(dates))
    ]
    return BalanceSeries(
        dates=dates,
        values=values,
        anchored=any(s.anchored for s in series),
        # Incomplet dès qu'un compte a une ancre manquante (ex. EUR sans taux CHF) :
        # sa valeur a été tracée à 0, on ne masque pas le trou.
        complete=all(s.complete for s in series),
    )


# =============================================================================
# Internals
# =============================================================================


def _subtract_months(d: datetime.date, months: int) -> datetime.date:
    """Subtract `months` from `d`, clamping day to the last valid day of the target month."""
    m = d.month - months
    year = d.year + (m - 1) // 12
    month = (m - 1) % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _snap_val(snap, in_chf: bool) -> Decimal | None:
    """Valeur d'ancre d'un snapshot. None = indisponible (ex. balance_chf pas encore converti)."""
    val = snap.balance_chf if in_chf else snap.authoritative_balance
    return cast("Decimal | None", val)


def _build_tx_cumsums(
    account,
    in_chf: bool,
) -> tuple[list[datetime.date], list[Decimal]]:
    """
    Build sorted cumulative-sum structure over transaction amounts for `account`.
    Returns (sorted_dates, cumsums) where cumsums[i] = Σ amounts up to sorted_dates[i].
    """
    from transactions.models import Transaction

    tx_by_date: dict[datetime.date, Decimal] = defaultdict(Decimal)
    for tx in Transaction.objects.filter(account=account).values(
        "date", "amount", "amount_chf"
    ):
        val = tx["amount_chf"] if in_chf else tx["amount"]
        if val is not None:
            tx_by_date[tx["date"]] += Decimal(str(val))

    sorted_dates = sorted(tx_by_date.keys())
    cumsums: list[Decimal] = []
    running = Decimal("0")
    for d in sorted_dates:
        running += tx_by_date[d]
        cumsums.append(running)

    return sorted_dates, cumsums


def _tx_range_sum(
    sorted_dates: list[datetime.date],
    cumsums: list[Decimal],
    after: datetime.date,
    through: datetime.date,
) -> Decimal:
    """Sum of tx amounts for dates strictly after `after` and up to `through` (inclusive)."""
    lo = bisect_right(sorted_dates, after)
    hi = bisect_right(sorted_dates, through)
    if hi == 0 or lo >= hi:
        return Decimal("0")
    before = cumsums[lo - 1] if lo > 0 else Decimal("0")
    return cumsums[hi - 1] - before


def _day_balance(
    day: datetime.date,
    snap_dates: list[datetime.date],
    snapshots: list,
    sorted_tx_dates: list[datetime.date],
    cumsums: list[Decimal],
    in_chf: bool,
) -> Decimal | None:
    """
    Solde de fin de journée pour `day` (ancrage hybride).
    Retourne None si l'ancre nécessaire est indisponible (ex. balance_chf NULL) —
    l'appelant signale alors `complete=False` plutôt que d'inventer un 0.
    """
    lo = bisect_right(snap_dates, day)
    left = snapshots[lo - 1] if lo > 0 else None
    right = snapshots[lo] if lo < len(snapshots) else None

    if left is None and right is None:
        return Decimal("0")

    if left is not None:
        anchor_val = _snap_val(left, in_chf)
        if anchor_val is None:
            return None  # ancre indisponible → jour non valorisable
        if left.date == day:
            return anchor_val
        # Forward walk: sum tx strictly after left.date up to day
        return anchor_val + _tx_range_sum(sorted_tx_dates, cumsums, left.date, day)

    # Ici left est None sans que (left ET right) le soient : right est forcément une ancre.
    # Narrowing explicite (pas d'assert : strippé sous python -O).
    if right is None:  # pragma: no cover — inatteignable, garde défensive
        return Decimal("0")
    anchor_val = _snap_val(right, in_chf)
    if anchor_val is None:
        return None
    # Backward walk from right: undo tx strictly after day up to right.date
    return anchor_val - _tx_range_sum(sorted_tx_dates, cumsums, day, right.date)

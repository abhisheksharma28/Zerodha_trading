"""Monthly-expiry selection and DTE for NIFTY options.

The strategy trades the **monthly** expiry, entering on a Friday when that
expiry is 39-43 calendar days out. "Monthly expiry" is defined as the last
listed weekly expiry that falls in a given calendar month (NSE index
weeklies currently expire Tuesday; the monthly is simply the final one of
the month). Everything is computed from the live NFO instrument master
(app.options.instruments_nfo) so we never assume a fixed weekday or a fixed
number of weeks per month.

DTE is calendar days by default (the strategy sheet says "39-43 DTE" and
those numbers only make sense as calendar days). A trading-day count is
available via ``trading_days_to_expiry`` for callers that want it, with an
injectable holiday set.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.options.instruments_nfo import load_option_contracts


@dataclass(frozen=True)
class ExpirySelection:
    expiry: date
    dte: int
    as_of: date
    is_friday: bool
    within_dte_window: bool
    eligible: bool
    reason: str


def listed_expiries(underlying: str) -> list[date]:
    return sorted({c.expiry for c in load_option_contracts(underlying)})


def monthly_expiries(underlying: str) -> list[date]:
    """One expiry per (year, month): the last listed expiry in that month."""
    by_month: dict[tuple[int, int], date] = {}
    for e in listed_expiries(underlying):
        key = (e.year, e.month)
        if key not in by_month or e > by_month[key]:
            by_month[key] = e
    return sorted(by_month.values())


def calendar_dte(expiry: date, as_of: date) -> int:
    return (expiry - as_of).days


def trading_days_to_expiry(
    expiry: date, as_of: date, *, holidays: Iterable[date] = ()
) -> int:
    """Trading days strictly after ``as_of`` up to and including ``expiry``."""
    hol = set(holidays)
    d = as_of + timedelta(days=1)
    n = 0
    while d <= expiry:
        if d.weekday() < 5 and d not in hol:
            n += 1
        d += timedelta(days=1)
    return n


def select_monthly_expiry(
    underlying: str,
    as_of: date,
    *,
    min_dte: int = 39,
    max_dte: int = 43,
    require_friday: bool = True,
) -> ExpirySelection:
    """Pick the monthly expiry whose calendar DTE from ``as_of`` lands in
    [min_dte, max_dte]. Returns an ExpirySelection whose ``eligible`` flag
    and ``reason`` say exactly why the day does or does not qualify — the
    caller (strategy) uses this verbatim in its not-eligible message."""
    is_friday = as_of.weekday() == 4
    candidates = [
        (e, calendar_dte(e, as_of))
        for e in monthly_expiries(underlying)
        if calendar_dte(e, as_of) > 0
    ]
    in_window = [(e, d) for (e, d) in candidates if min_dte <= d <= max_dte]

    if not candidates:
        return ExpirySelection(as_of, 0, as_of, is_friday, False, False,
                               "No future monthly expiry listed for the underlying.")

    if in_window:
        # If several monthlies fall in the window (unusual), take the nearest.
        expiry, dte = min(in_window, key=lambda t: t[1])
        within = True
    else:
        # Nearest monthly, for reporting the actual DTE in the reason string.
        expiry, dte = min(candidates, key=lambda t: abs(t[1] - (min_dte + max_dte) // 2))
        within = False

    if require_friday and not is_friday:
        reason = f"Not a Friday (weekday {as_of.strftime('%A')})."
        eligible = False
    elif not within:
        reason = f"DTE = {dte} for {expiry.isoformat()}, outside [{min_dte}, {max_dte}]."
        eligible = False
    else:
        reason = f"Eligible: Friday, monthly expiry {expiry.isoformat()} at DTE {dte}."
        eligible = True

    return ExpirySelection(
        expiry=expiry, dte=dte, as_of=as_of, is_friday=is_friday,
        within_dte_window=within, eligible=eligible, reason=reason,
    )

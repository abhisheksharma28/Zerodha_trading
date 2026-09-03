"""Completed-month returns and the three seasonal-edge measures.

Documented conventions (kept consistent everywhere):

* Monthly return = last close of the month / last close of the previous
  month − 1  (arithmetic simple return, not log).
* Only *completed* calendar months are used. The final month of a series
  is treated as partial and dropped; future months do not exist.
* A month needs the previous month present to have a return (no gap-filling).
* "Seasonal edge" measures are all computed per (sector, year, month):
    A. own edge        = month return − that year's mean completed-month return
    B. market-adjusted = month return − NIFTY 50's return that same month
    C. cross-sectional = month return − median return across all sectors that
                         month  (+ a 1..N cross-sectional rank)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.seasonality import MARKET_INDEX


def _key(ts: Any) -> datetime:
    s = str(ts)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.fromisoformat(s[:19]).replace(tzinfo=None)


def monthly_closes(bars: list[Any]) -> dict[tuple[int, int], float]:
    """(-> {(year, month): last close of that month}). The last (partial)
    month of the series is excluded."""
    by: dict[tuple[int, int], tuple[datetime, float]] = {}
    for b in bars:
        d = _key(b.timestamp)
        c = float(getattr(b, "close", 0.0) or 0.0)
        if c <= 0:
            continue
        ym = (d.year, d.month)
        if ym not in by or d > by[ym][0]:
            by[ym] = (d, c)
    if not by:
        return {}
    last_ym = max(by)
    return {ym: v[1] for ym, v in by.items() if ym != last_ym}


def monthly_returns(bars: list[Any]) -> dict[tuple[int, int], float]:
    """(-> {(year, month): simple return %}) for every completed month that
    has the previous month present."""
    closes = monthly_closes(bars)
    out: dict[tuple[int, int], float] = {}
    for (y, m), c in closes.items():
        pm = (y - 1, 12) if m == 1 else (y, m - 1)
        if pm in closes and closes[pm] > 0:
            out[(y, m)] = (c / closes[pm] - 1.0) * 100.0
    return out


def own_edges(mrets: dict[tuple[int, int], float]) -> dict[tuple[int, int], float]:
    """A. month return minus that calendar year's mean completed-month return.
    Only years with >= 6 completed months contribute (near-complete year)."""
    by_year: dict[int, list[tuple[int, float]]] = {}
    for (y, m), r in mrets.items():
        by_year.setdefault(y, []).append((m, r))
    out: dict[tuple[int, int], float] = {}
    for y, items in by_year.items():
        if len(items) < 6:
            continue
        year_mean = sum(r for _m, r in items) / len(items)
        for m, r in items:
            out[(y, m)] = r - year_mean
    return out


def build_panel(
    bars_by_sector: dict[str, list[Any]],
    *,
    sectors: list[str] | None = None,
) -> dict[str, Any]:
    """The full seasonal panel used by every downstream module.

    Returns::

        {
          "sectors": [...],
          "returns":  {sector: {(y,m): ret%}},
          "own":      {sector: {(y,m): own edge}},
          "market_adj": {sector: {(y,m): sector ret − NIFTY 50 ret}},
          "cross":    {sector: {(y,m): sector ret − median across sectors}},
          "cross_rank": {sector: {(y,m): 1..N, 1 = strongest that month}},
          "market_returns": {(y,m): NIFTY 50 ret%},
        }
    """
    names = list(sectors or [s for s in bars_by_sector if s != MARKET_INDEX])
    rets = {s: monthly_returns(bars_by_sector[s]) for s in names if s in bars_by_sector}
    market = monthly_returns(bars_by_sector.get(MARKET_INDEX, []))

    own = {s: own_edges(r) for s, r in rets.items()}

    market_adj: dict[str, dict[tuple[int, int], float]] = {}
    for s, r in rets.items():
        market_adj[s] = {ym: v - market[ym] for ym, v in r.items() if ym in market}

    # cross-sectional: per month, sector return minus the median across all
    # sectors that have that month
    all_months: set[tuple[int, int]] = set()
    for r in rets.values():
        all_months.update(r)
    cross: dict[str, dict[tuple[int, int], float]] = {s: {} for s in rets}
    cross_rank: dict[str, dict[tuple[int, int], int]] = {s: {} for s in rets}
    for ym in all_months:
        present = [(s, rets[s][ym]) for s in rets if ym in rets[s]]
        if len(present) < 3:
            continue
        vals = sorted(v for _s, v in present)
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        ranked = sorted(present, key=lambda kv: kv[1], reverse=True)
        for rank, (s, v) in enumerate(ranked, 1):
            cross[s][ym] = v - med
            cross_rank[s][ym] = rank

    return {
        "sectors": names,
        "returns": rets,
        "own": own,
        "market_adj": market_adj,
        "cross": cross,
        "cross_rank": cross_rank,
        "market_returns": market,
    }

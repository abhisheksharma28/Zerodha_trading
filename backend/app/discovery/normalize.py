"""Returns + currency normalisation for the discovery store.

``returns_frame`` gives the later phases an aligned return matrix for a
set of symbols, in USD or INR, at monthly / weekly / daily frequency,
with local vs FX-adjusted returns kept distinct.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.discovery import DiscoveryBar, DiscoveryFxRate, DiscoveryInstrument

_FX_FOR = {"INR": "USD/INR"}  # target currency -> pair that multiplies a USD price


def _prices(db: Session, symbols: list[str]) -> dict[str, list[tuple[date, float]]]:
    rows = db.execute(
        select(DiscoveryInstrument.symbol, DiscoveryBar.d, DiscoveryBar.close)
        .join(DiscoveryBar, DiscoveryBar.instrument_id == DiscoveryInstrument.id)
        .where(DiscoveryInstrument.symbol.in_(symbols))
        .order_by(DiscoveryInstrument.symbol, DiscoveryBar.d)
    ).all()
    out: dict[str, list[tuple[date, float]]] = {}
    for sym, d, c in rows:
        out.setdefault(sym, []).append((d, float(c)))
    return out


def _fx(db: Session, pair: str) -> dict[date, float]:
    rows = db.execute(
        select(DiscoveryFxRate.d, DiscoveryFxRate.rate).where(DiscoveryFxRate.pair == pair)
    ).all()
    return {d: float(r) for d, r in rows}


def _fx_on_or_before(fx: dict[date, float], d: date) -> float | None:
    if d in fx:
        return fx[d]
    prior = [x for x in fx if x <= d]
    return fx[max(prior)] if prior else None


def returns_frame(
    db: Session,
    symbols: list[str],
    *,
    currency: str = "USD",
    freq: str = "monthly",  # kept for the API contract; the store is already at bar_interval
    kind: str = "simple",   # simple | log
    fx_adjust: bool = True,
) -> dict[str, Any]:
    """Aligned return matrix on the common date set of ``symbols``.

    -> {"dates": [...], "returns": {sym: [...]}, "prices": {sym: [...]},
        "currency": currency, "fx_adjusted": bool, "missing": [...]}
    """
    del freq  # the store is monthly in phase 1; hook for later resampling
    px = _prices(db, symbols)
    missing = [s for s in symbols if s not in px or len(px[s]) < 3]
    have = [s for s in symbols if s not in missing]
    if not have:
        return {"dates": [], "returns": {}, "prices": {}, "currency": currency,
                "fx_adjusted": False, "missing": missing}

    fx_map: dict[date, float] | None = None
    do_fx = fx_adjust and currency.upper() != "USD" and currency.upper() in _FX_FOR
    if do_fx:
        fx_map = _fx(db, _FX_FOR[currency.upper()])
        if not fx_map:
            do_fx = False

    # common date set = intersection of every requested symbol's dates
    common: set[date] | None = None
    for s in have:
        ds = {d for d, _ in px[s]}
        common = ds if common is None else (common & ds)
    dates = sorted(common or set())
    if len(dates) < 3:
        return {"dates": [], "returns": {}, "prices": {}, "currency": currency,
                "fx_adjusted": do_fx, "missing": missing + ["<no common history>"]}

    prices: dict[str, list[float]] = {}
    returns: dict[str, list[float]] = {}
    for s in have:
        pmap = dict(px[s])
        line = []
        for d in dates:
            p = pmap[d]
            if do_fx and fx_map is not None:
                rate = _fx_on_or_before(fx_map, d)
                p = p * rate if rate else p
            line.append(p)
        prices[s] = [round(v, 6) for v in line]
        r = []
        for i in range(1, len(line)):
            a, b = line[i - 1], line[i]
            if a <= 0:
                r.append(0.0)
            elif kind == "log":
                r.append(math.log(b / a))
            else:
                r.append(b / a - 1.0)
        returns[s] = [round(v, 8) for v in r]

    return {
        "dates": [d.isoformat() for d in dates],
        "return_dates": [d.isoformat() for d in dates[1:]],
        "returns": returns,
        "prices": prices,
        "currency": currency.upper(),
        "fx_adjusted": do_fx,
        "kind": kind,
        "missing": missing,
    }

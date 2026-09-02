"""Volume-Weighted Average Price with standard-deviation bands.

Exact from candles - unlike the volume profile there is no approximation
here beyond using the bar's typical price (H+L+C)/3 as the fill proxy for
that bar's volume, which is the standard VWAP convention.

VWAP_t   = sum(tp_i * v_i) / sum(v_i)          for i = anchor..t
var_t    = sum(v_i * tp_i^2) / sum(v_i) - VWAP_t^2   (volume-weighted)
band k   = VWAP_t +/- k * sqrt(max(var_t, 0))

Anchor: pass ``anchor_ts`` for anchored VWAP (e.g. a swing high, an event).
``session_anchor_ts`` returns the first candle at/after the most recent
09:15 IST open present in the data.
"""

from __future__ import annotations

import math

from app.orderflow.types import Candle, DataTier, VwapPoint, VwapSeries

_IST_OFFSET = 5 * 3600 + 30 * 60
_SESSION_OPEN_SEC = 9 * 3600 + 15 * 60  # 09:15 in IST seconds-of-day


def session_anchor_ts(candles: list[Candle]) -> int | None:
    """Epoch-sec of the first bar of the last trading day in ``candles``.
    ``ts`` is already IST-shifted, so day/seconds math is plain modulo."""
    if not candles:
        return None
    last_day = (candles[-1].ts // 86400) * 86400
    open_ts = last_day + _SESSION_OPEN_SEC
    same_day = [c.ts for c in candles if c.ts >= open_ts and c.ts // 86400 == candles[-1].ts // 86400]
    if same_day:
        return min(same_day)
    # data may not start at the open; fall back to the first bar of that day
    day_bars = [c.ts for c in candles if c.ts // 86400 == candles[-1].ts // 86400]
    return min(day_bars) if day_bars else candles[0].ts


def vwap_series(
    candles: list[Candle],
    *,
    anchor_ts: int | None = None,
    band_multiples: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> VwapSeries:
    rows = sorted((c for c in candles), key=lambda c: c.ts)
    if anchor_ts is not None:
        rows = [c for c in rows if c.ts >= anchor_ts]
    anchor = anchor_ts if anchor_ts is not None else (rows[0].ts if rows else 0)

    method = (
        "Cumulative sum(typical_price * volume) / sum(volume) from the anchor; "
        "bands are k * volume-weighted std dev of typical price about VWAP."
    )

    pts: list[VwapPoint] = []
    cum_pv = 0.0
    cum_v = 0.0
    cum_pv2 = 0.0
    for c in rows:
        tp = (c.high + c.low + c.close) / 3.0
        v = max(c.volume, 0.0)
        cum_pv += tp * v
        cum_v += v
        cum_pv2 += tp * tp * v
        if cum_v <= 0:
            continue
        vwap = cum_pv / cum_v
        var = max(cum_pv2 / cum_v - vwap * vwap, 0.0)
        sd = math.sqrt(var)
        bands: dict[str, float] = {}
        for k in band_multiples:
            tag = str(int(k)) if float(k).is_integer() else str(k).replace(".", "_")
            bands[f"upper{tag}"] = vwap + k * sd
            bands[f"lower{tag}"] = vwap - k * sd
        pts.append(VwapPoint(ts=c.ts, vwap=vwap, bands=bands))

    return VwapSeries(
        anchor_ts=anchor,
        points=pts,
        band_multiples=list(band_multiples),
        tier=DataTier.LIMITED,
        method=method,
    )

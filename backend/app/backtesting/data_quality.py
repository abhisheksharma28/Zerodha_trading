"""Pre-run data-quality checks for backtest candles.

The engine must not silently paper over bad market data — a fabricated or
mis-ordered candle can invent trades that never could have happened. This
module inspects the candle set and reports problems; the caller decides
whether hard errors (invalid OHLC, duplicate or out-of-order timestamps)
block the run while soft warnings (gaps, thin history, naive timestamps)
only annotate it. Nothing here modifies the data.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any

from app.strategies.base import Bar

_MIN_REASONABLE_BARS = 30


def _to_dt(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts
    s = str(ts).strip().replace("Z", "+00:00")
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _check_one(symbol: str, bars: list[Bar]) -> dict[str, Any]:
    n = len(bars)
    issues: dict[str, Any] = {
        "symbol": symbol,
        "bars": n,
        "duplicate_timestamps": 0,
        "out_of_order": 0,
        "invalid_ohlc": 0,
        "non_positive_price": 0,
        "negative_volume": 0,
        "naive_timestamps": 0,
        "suspicious_gaps": 0,
        "max_gap_ratio": 0.0,
        "insufficient_history": n < _MIN_REASONABLE_BARS,
    }
    seen: set[Any] = set()
    dts: list[datetime] = []
    prev_dt: datetime | None = None

    for b in bars:
        o, h, low, c = float(b.open), float(b.high), float(b.low), float(b.close)
        if min(o, h, low, c) <= 0:
            issues["non_positive_price"] += 1
        if h < low or h < o - 1e-9 or h < c - 1e-9 or low > o + 1e-9 or low > c + 1e-9:
            issues["invalid_ohlc"] += 1
        if (b.volume or 0) < 0:
            issues["negative_volume"] += 1

        key = str(b.timestamp)
        if key in seen:
            issues["duplicate_timestamps"] += 1
        seen.add(key)

        d = _to_dt(b.timestamp)
        if d is None:
            continue
        if d.tzinfo is None:
            issues["naive_timestamps"] += 1
        if prev_dt is not None and d < prev_dt:
            issues["out_of_order"] += 1
        prev_dt = d
        dts.append(d)

    if len(dts) >= 3:
        deltas = [(dts[i] - dts[i - 1]).total_seconds() for i in range(1, len(dts))]
        deltas = [x for x in deltas if x > 0]
        if deltas:
            med = median(deltas)
            biggest = max(deltas)
            issues["max_gap_ratio"] = round(biggest / med, 2) if med > 0 else 0.0
            # a "gap" here is a delta well beyond the typical spacing; weekend /
            # overnight breaks in daily data are expected, so the threshold is
            # deliberately loose (5x the median spacing).
            issues["suspicious_gaps"] = sum(1 for x in deltas if med > 0 and x > 5 * med)

    return issues


def validate_candles(candles_by_instrument: dict[str, list[Bar]]) -> dict[str, Any]:
    per_symbol = [_check_one(sym, bars) for sym, bars in candles_by_instrument.items()]

    errors: list[str] = []
    warnings: list[str] = []
    for s in per_symbol:
        sym = s["symbol"]
        if s["bars"] == 0:
            errors.append(f"{sym}: no candles")
        if s["invalid_ohlc"]:
            errors.append(f"{sym}: {s['invalid_ohlc']} bars with invalid OHLC (high<low etc.)")
        if s["non_positive_price"]:
            errors.append(f"{sym}: {s['non_positive_price']} bars with a non-positive price")
        if s["duplicate_timestamps"]:
            errors.append(f"{sym}: {s['duplicate_timestamps']} duplicate timestamps")
        if s["out_of_order"]:
            errors.append(f"{sym}: {s['out_of_order']} out-of-order timestamps")
        if s["negative_volume"]:
            warnings.append(f"{sym}: {s['negative_volume']} bars with negative volume")
        if s["insufficient_history"]:
            warnings.append(f"{sym}: only {s['bars']} bars — thin history for most strategies")
        if s["naive_timestamps"]:
            warnings.append(f"{sym}: {s['naive_timestamps']} timestamps without a timezone")
        if s["suspicious_gaps"]:
            warnings.append(
                f"{sym}: {s['suspicious_gaps']} large gaps (up to {s['max_gap_ratio']}x the "
                "typical spacing) — possible missing candles"
            )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "per_symbol": per_symbol,
    }

"""Candlestick reversal / continuation patterns, per the classic spec:
Hammer, Hanging Man, Bullish/Bearish Engulfing, Morning/Evening Star,
Bullish/Bearish Piercing, Bullish/Bearish Harami, Bullish/Bearish Doji,
double top / bottom and the 1-2-3 continuation.

Each detector needs the prevailing short-term trend as context (a hammer is
only a hammer at the end of a downtrend). All measured off the last few
closed bars - no tick data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Pattern:
    name: str
    label: str
    direction: str        # "BULLISH" | "BEARISH"
    strength: float        # 0..1 rough confidence in the shape
    entry: float
    stop: float
    at_index: int          # bar index of the confirming candle


@dataclass
class CandleReport:
    patterns: list[Pattern] = field(default_factory=list)   # most recent first
    trend: str = "RANGE"                                    # UP | DOWN | RANGE

    @property
    def latest(self) -> Pattern | None:
        return self.patterns[0] if self.patterns else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "patterns": [
                {"name": p.name, "label": p.label, "direction": p.direction,
                 "strength": round(p.strength, 2), "entry": round(p.entry, 2),
                 "stop": round(p.stop, 2)}
                for p in self.patterns[:4]
            ],
        }


# --- primitives --------------------------------------------------------

def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, lo: float) -> float:
    return max(h - lo, 1e-9)


def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_wick(o: float, lo: float, c: float) -> float:
    return min(o, c) - lo


def _bull(o: float, c: float) -> bool:
    return c > o


def _short_trend(closes: list[float], n: int = 10) -> str:
    if len(closes) < n + 1:
        return "RANGE"
    window = closes[-n - 1 :]
    slope = (window[-1] - window[0]) / max(abs(window[0]), 1e-9)
    if slope > 0.015:
        return "UP"
    if slope < -0.015:
        return "DOWN"
    return "RANGE"


# --- single / two / three-candle detectors ---------------------------

def _hammer_family(bars: list[dict], i: int, trend: str) -> Pattern | None:
    o, h, lo, c = bars[i]["open"], bars[i]["high"], bars[i]["low"], bars[i]["close"]
    body, rng = _body(o, c), _range(h, lo)
    low_w, up_w = _lower_wick(o, lo, c), _upper_wick(o, h, c)
    if body <= 0 or body / rng > 0.35:
        return None
    if low_w < 2.0 * body or up_w > body:
        return None
    if trend == "DOWN":
        return Pattern("hammer", "Hammer", "BULLISH", min(1.0, low_w / (3 * body)), c, lo, i)
    if trend == "UP":
        return Pattern("hanging_man", "Hanging Man", "BEARISH", min(1.0, low_w / (3 * body)), c, h, i)
    return None


def _shooting_star(bars: list[dict], i: int, trend: str) -> Pattern | None:
    o, h, lo, c = bars[i]["open"], bars[i]["high"], bars[i]["low"], bars[i]["close"]
    body, rng = _body(o, c), _range(h, lo)
    low_w, up_w = _lower_wick(o, lo, c), _upper_wick(o, h, c)
    if body <= 0 or body / rng > 0.35 or up_w < 2.0 * body or low_w > body:
        return None
    if trend == "UP":
        return Pattern("shooting_star", "Shooting Star", "BEARISH", min(1.0, up_w / (3 * body)), c, h, i)
    return None


def _engulfing(bars: list[dict], i: int, trend: str) -> Pattern | None:
    if i < 1:
        return None
    p, q = bars[i - 1], bars[i]
    pb, qb = _body(p["open"], p["close"]), _body(q["open"], q["close"])
    if qb < pb * 1.05:
        return None
    # bullish: prev red, curr green, curr body covers prev body
    if (trend == "DOWN" and not _bull(p["open"], p["close"]) and _bull(q["open"], q["close"])
            and q["close"] >= p["open"] and q["open"] <= p["close"]):
        return Pattern("bullish_engulfing", "Bullish Engulfing", "BULLISH",
                       min(1.0, qb / (pb + 1e-9) - 1), q["close"], min(q["low"], p["low"]), i)
    if (trend == "UP" and _bull(p["open"], p["close"]) and not _bull(q["open"], q["close"])
            and q["open"] >= p["close"] and q["close"] <= p["open"]):
        return Pattern("bearish_engulfing", "Bearish Engulfing", "BEARISH",
                       min(1.0, qb / (pb + 1e-9) - 1), q["close"], max(q["high"], p["high"]), i)
    return None


def _piercing(bars: list[dict], i: int, trend: str) -> Pattern | None:
    if i < 1:
        return None
    p, q = bars[i - 1], bars[i]
    p_mid = (p["open"] + p["close"]) / 2
    if (trend == "DOWN" and not _bull(p["open"], p["close"]) and _bull(q["open"], q["close"])
            and q["open"] < p["close"] and p_mid < q["close"] < p["open"]):
        return Pattern("bullish_piercing", "Bullish Piercing", "BULLISH", 0.6, q["close"], q["low"], i)
    if (trend == "UP" and _bull(p["open"], p["close"]) and not _bull(q["open"], q["close"])
            and q["open"] > p["close"] and p_mid > q["close"] > p["open"]):
        return Pattern("bearish_piercing", "Dark Cloud Cover", "BEARISH", 0.6, q["close"], q["high"], i)
    return None


def _harami(bars: list[dict], i: int, trend: str) -> Pattern | None:
    if i < 1:
        return None
    p, q = bars[i - 1], bars[i]
    pb, qb = _body(p["open"], p["close"]), _body(q["open"], q["close"])
    if pb <= 0 or qb > pb * 0.6:
        return None
    p_hi, p_lo = max(p["open"], p["close"]), min(p["open"], p["close"])
    inside = p_lo <= q["open"] <= p_hi and p_lo <= q["close"] <= p_hi
    if not inside:
        return None
    if trend == "DOWN" and not _bull(p["open"], p["close"]) and _bull(q["open"], q["close"]):
        return Pattern("bullish_harami", "Bullish Harami", "BULLISH", 0.5, q["close"], p["low"], i)
    if trend == "UP" and _bull(p["open"], p["close"]) and not _bull(q["open"], q["close"]):
        return Pattern("bearish_harami", "Bearish Harami", "BEARISH", 0.5, q["close"], p["high"], i)
    return None


def _doji_reversal(bars: list[dict], i: int, trend: str) -> Pattern | None:
    if i < 1:
        return None
    d, q = bars[i - 1], bars[i]
    if _body(d["open"], d["close"]) / _range(d["high"], d["low"]) > 0.1:
        return None  # bar i-1 isn't a doji
    if trend == "DOWN" and _bull(q["open"], q["close"]) and q["close"] > d["high"]:
        return Pattern("bullish_doji", "Doji Reversal (bull)", "BULLISH", 0.5, q["close"], d["low"], i)
    if trend == "UP" and not _bull(q["open"], q["close"]) and q["close"] < d["low"]:
        return Pattern("bearish_doji", "Doji Reversal (bear)", "BEARISH", 0.5, q["close"], d["high"], i)
    return None


def _star(bars: list[dict], i: int, trend: str) -> Pattern | None:
    if i < 2:
        return None
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    ab = _body(a["open"], a["close"])
    bb = _body(b["open"], b["close"])
    if ab <= 0 or bb > ab * 0.5:
        return None
    a_mid = (a["open"] + a["close"]) / 2
    if (trend == "DOWN" and not _bull(a["open"], a["close"]) and _bull(c["open"], c["close"])
            and c["close"] > a_mid):
        return Pattern("morning_star", "Morning Star", "BULLISH", 0.75, c["close"], min(b["low"], c["low"]), i)
    if (trend == "UP" and _bull(a["open"], a["close"]) and not _bull(c["open"], c["close"])
            and c["close"] < a_mid):
        return Pattern("evening_star", "Evening Star", "BEARISH", 0.75, c["close"], max(b["high"], c["high"]), i)
    return None


_DETECTORS = (_hammer_family, _shooting_star, _engulfing, _piercing, _harami, _doji_reversal, _star)


def analyse(bars: list[dict[str, Any]], *, lookback: int = 4) -> CandleReport:
    """``bars``: {open,high,low,close} dicts oldest-first. Scans the last
    ``lookback`` closed candles for a pattern."""
    n = len(bars)
    if n < 12:
        return CandleReport()
    closes = [float(b["close"]) for b in bars]
    trend = _short_trend(closes)
    found: list[Pattern] = []
    for i in range(n - 1, max(11, n - 1 - lookback), -1):
        for det in _DETECTORS:
            p = det(bars, i, trend)
            if p is not None:
                found.append(p)
    # de-dupe by name, keep the most recent
    seen: set[str] = set()
    uniq: list[Pattern] = []
    for p in found:
        if p.name not in seen:
            seen.add(p.name)
            uniq.append(p)
    return CandleReport(patterns=uniq, trend=trend)

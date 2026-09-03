"""Classic multi-swing chart patterns, read off the fractal pivot sequence
that :mod:`app.market_scanner.structure` already produces.

Per Kirkpatrick / Fidelity's "Identifying Chart Patterns": a pattern is
*not active until price breaks out* of it, and every pattern has a
measured-move target (project the pattern's height from the breakout).
This module only reports a pattern as ``confirmed`` once a real breakout
close has happened; otherwise it is ``forming`` and carries no signal
weight.

Covered: double / triple top & bottom, head-and-shoulders (+ inverse),
ascending / descending / symmetrical triangle, rectangle. Each is a
horizontal-congestion or converging structure with a clean target formula.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.market_scanner.structure import StructureReport, Swing


@dataclass(frozen=True)
class ChartPattern:
    name: str
    label: str
    direction: str          # "BULLISH" | "BEARISH"
    status: str             # "forming" | "confirmed"
    strength: float          # 0..1
    breakout: float          # the level price must clear / has cleared
    target: float            # measured-move objective
    stop: float              # invalidation level
    pivots: int              # how many swings the pattern spans

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "direction": self.direction,
            "status": self.status, "strength": round(self.strength, 2),
            "breakout": round(self.breakout, 2), "target": round(self.target, 2),
            "stop": round(self.stop, 2),
        }


@dataclass
class ChartPatternReport:
    patterns: list[ChartPattern] = field(default_factory=list)  # most recent first

    @property
    def latest(self) -> ChartPattern | None:
        return self.patterns[0] if self.patterns else None

    def as_dict(self) -> dict[str, Any]:
        return {"patterns": [p.as_dict() for p in self.patterns[:4]]}


def _close_to(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def _tol(atr: float, price: float) -> float:
    """Relative tolerance for "roughly the same price": ~0.6 ATR, floored
    at 1.2% and capped at 4%."""
    rel = (0.6 * atr / price) if (atr and price) else 0.02
    return max(0.012, min(0.04, rel))


def _double(seq: list[Swing], closes: list[float], atr: float) -> ChartPattern | None:
    """Double top: H .. L .. H at ~equal highs; confirmed on a close below
    the middle L. Double bottom is the mirror."""
    if len(seq) < 3:
        return None
    a, b, c = seq[-3], seq[-2], seq[-1]
    price = closes[-1]
    tol = _tol(atr, price)
    if a.kind == "H" and c.kind == "H" and b.kind == "L" and _close_to(a.price, c.price, tol):
        height = ((a.price + c.price) / 2) - b.price
        if height <= 0:
            return None
        confirmed = price < b.price
        return ChartPattern(
            "double_top", "Double Top", "BEARISH",
            "confirmed" if confirmed else "forming",
            0.7 if confirmed else 0.4, b.price, b.price - height,
            max(a.price, c.price), 3,
        )
    if a.kind == "L" and c.kind == "L" and b.kind == "H" and _close_to(a.price, c.price, tol):
        height = b.price - ((a.price + c.price) / 2)
        if height <= 0:
            return None
        confirmed = price > b.price
        return ChartPattern(
            "double_bottom", "Double Bottom", "BULLISH",
            "confirmed" if confirmed else "forming",
            0.7 if confirmed else 0.4, b.price, b.price + height,
            min(a.price, c.price), 3,
        )
    return None


def _windows5(seq: list[Swing]) -> list[list[Swing]]:
    """Every 5-pivot window in roughly the last 8 pivots, most recent first."""
    out: list[list[Swing]] = []
    for start in range(len(seq) - 5, max(-1, len(seq) - 9), -1):
        if start >= 0:
            out.append(seq[start : start + 5])
    return out


def _triple(seq: list[Swing], closes: list[float], atr: float) -> ChartPattern | None:
    price = closes[-1]
    tol = _tol(atr, price)
    for p in _windows5(seq):
        kinds = "".join(s.kind for s in p)
        if (kinds == "HLHLH" and _close_to(p[0].price, p[2].price, tol)
                and _close_to(p[2].price, p[4].price, tol)):
            trough = min(p[1].price, p[3].price)
            height = max(p[0].price, p[2].price, p[4].price) - trough
            confirmed = price < trough
            return ChartPattern(
                "triple_top", "Triple Top", "BEARISH", "confirmed" if confirmed else "forming",
                0.75 if confirmed else 0.4, trough, trough - height, max(s.price for s in p), 5,
            )
        if (kinds == "LHLHL" and _close_to(p[0].price, p[2].price, tol)
                and _close_to(p[2].price, p[4].price, tol)):
            peak = max(p[1].price, p[3].price)
            height = peak - min(p[0].price, p[2].price, p[4].price)
            confirmed = price > peak
            return ChartPattern(
                "triple_bottom", "Triple Bottom", "BULLISH", "confirmed" if confirmed else "forming",
                0.75 if confirmed else 0.4, peak, peak + height, min(s.price for s in p), 5,
            )
    return None


def _head_shoulders(seq: list[Swing], closes: list[float], atr: float) -> ChartPattern | None:
    """H-S top: H L H L H where the centre H is the highest, the outer Hs are
    ~equal shoulders and the two Ls form the neckline. Confirmed on a close
    through the neckline. Target = (head − neckline) projected."""
    price = closes[-1]
    tol = _tol(atr, price) * 1.3
    for p in _windows5(seq):
        kinds = "".join(s.kind for s in p)
        if kinds == "HLHLH":
            ls, head, rs = p[0].price, p[2].price, p[4].price
            neck = (p[1].price + p[3].price) / 2
            if head > ls and head > rs and _close_to(ls, rs, tol) and head > neck:
                height = head - neck
                confirmed = price < min(p[1].price, p[3].price)
                return ChartPattern(
                    "head_shoulders_top", "Head & Shoulders", "BEARISH",
                    "confirmed" if confirmed else "forming",
                    0.8 if confirmed else 0.45, neck, neck - height, head, 5,
                )
        if kinds == "LHLHL":
            ls, head, rs = p[0].price, p[2].price, p[4].price
            neck = (p[1].price + p[3].price) / 2
            if head < ls and head < rs and _close_to(ls, rs, tol) and head < neck:
                height = neck - head
                confirmed = price > max(p[1].price, p[3].price)
                return ChartPattern(
                    "head_shoulders_bottom", "Inverse Head & Shoulders", "BULLISH",
                    "confirmed" if confirmed else "forming",
                    0.8 if confirmed else 0.45, neck, neck + height, head, 5,
                )
    return None


def _triangle_or_rectangle(seq: list[Swing], closes: list[float], atr: float) -> ChartPattern | None:
    """Read the last two highs and last two lows: flat-vs-sloping tells
    ascending / descending / symmetrical triangle or a rectangle."""
    hs = [s for s in seq if s.kind == "H"][-2:]
    ls = [s for s in seq if s.kind == "L"][-2:]
    if len(hs) < 2 or len(ls) < 2:
        return None
    price = closes[-1]
    tol = _tol(atr, price)
    hi_flat = _close_to(hs[0].price, hs[1].price, tol)
    lo_flat = _close_to(ls[0].price, ls[1].price, tol)
    hi_down = hs[1].price < hs[0].price and not hi_flat
    lo_up = ls[1].price > ls[0].price and not lo_flat
    top = max(hs[0].price, hs[1].price)
    bot = min(ls[0].price, ls[1].price)
    height = top - bot
    if height <= 0:
        return None

    if hi_flat and lo_up:
        res = (hs[0].price + hs[1].price) / 2
        confirmed = price > res
        return ChartPattern("ascending_triangle", "Ascending Triangle", "BULLISH",
                            "confirmed" if confirmed else "forming",
                            0.7 if confirmed else 0.4, res, res + height, bot, 4)
    if lo_flat and hi_down:
        sup = (ls[0].price + ls[1].price) / 2
        confirmed = price < sup
        return ChartPattern("descending_triangle", "Descending Triangle", "BEARISH",
                            "confirmed" if confirmed else "forming",
                            0.7 if confirmed else 0.4, sup, sup - height, top, 4)
    if hi_down and lo_up:
        # symmetrical - direction taken from the actual breakout only
        if price > hs[1].price:
            return ChartPattern("symmetrical_triangle", "Symmetrical Triangle (up)", "BULLISH",
                                "confirmed", 0.6, hs[1].price, hs[1].price + height, bot, 4)
        if price < ls[1].price:
            return ChartPattern("symmetrical_triangle", "Symmetrical Triangle (down)", "BEARISH",
                                "confirmed", 0.6, ls[1].price, ls[1].price - height, top, 4)
        return None
    if hi_flat and lo_flat and height > 0.02 * price:
        if price > top:
            return ChartPattern("rectangle", "Rectangle (breakout up)", "BULLISH",
                                "confirmed", 0.55, top, top + height, bot, 4)
        if price < bot:
            return ChartPattern("rectangle", "Rectangle (breakout down)", "BEARISH",
                                "confirmed", 0.55, bot, bot - height, top, 4)
    return None


_DETECTORS = (_head_shoulders, _triple, _double, _triangle_or_rectangle)


def analyse(bars: list[dict[str, Any]], structure: StructureReport) -> ChartPatternReport:
    """Detect chart patterns from ``structure.swings`` (the alternating pivot
    sequence). Needs at least a handful of pivots and 30 bars."""
    if len(bars) < 30 or len(structure.swings) < 3:
        return ChartPatternReport()
    closes = [float(b["close"]) for b in bars]
    atr = _rough_atr(bars)
    swings = structure.swings
    # also try with the last pivot dropped: a small, still-unconfirmed swing
    # printed during the breakout shouldn't hide the pattern behind it
    windows = [swings, swings[:-1]] if len(swings) >= 4 else [swings]
    found: list[ChartPattern] = []
    seen: set[str] = set()
    for det in _DETECTORS:
        for seq in windows:
            p = det(seq, closes, atr)
            if p is not None and p.name not in seen:
                seen.add(p.name)
                found.append(p)
                break
    # confirmed patterns first, then by strength
    found.sort(key=lambda p: (p.status != "confirmed", -p.strength))
    return ChartPatternReport(patterns=found)


def _rough_atr(bars: list[dict[str, Any]], period: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(bars)):
        h, lo, pc = float(bars[i]["high"]), float(bars[i]["low"]), float(bars[i - 1]["close"])
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    tail = trs[-period:]
    return sum(tail) / len(tail) if tail else 0.0

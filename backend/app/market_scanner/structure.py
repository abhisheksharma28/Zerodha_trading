"""Systematic price-action / market-structure reading from OHLC bars.

The discretionary "smart-money" concepts have no single canonical
definition. These are explicit, reproducible proxies computed only from
candles (Kite gives no tick data), and are labelled as approximations
wherever they surface in the UI:

* swing point   - a fractal pivot: a bar whose high (low) is the highest
                  (lowest) of ``left`` bars before and ``right`` bars after.
* market        - UP while swings print higher-highs and higher-lows,
  structure       DOWN on lower-highs and lower-lows, else RANGE.
* BOS           - a candle *closes* beyond the most recent opposing swing
                  in the direction of the prevailing structure.
* CHoCH         - the first such close *against* the prevailing structure
                  (a potential trend change).
* FVG           - a 3-candle imbalance: bullish when bar i's low is above
                  bar i-2's high (price skipped a band); mitigated once
                  later price trades back through that band.
* order block   - the last opposing candle before the impulse that caused
                  a BOS; its range is the zone. Mitigated once revisited.
* liquidity     - a wick beyond the prior ``lookback``-bar extreme that
  sweep           closes back inside (stop-run) - recent bars only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Swing:
    index: int
    price: float
    kind: str  # "H" | "L"


@dataclass(frozen=True)
class Zone:
    kind: str  # "bullish" | "bearish"
    top: float
    bottom: float
    index: int
    mitigated: bool

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(frozen=True)
class StructureReport:
    trend: str  # "UP" | "DOWN" | "RANGE"
    last_break: str | None  # "BOS_UP" | "BOS_DOWN" | "CHOCH_UP" | "CHOCH_DOWN"
    last_break_index: int | None
    swing_high: float | None
    swing_low: float | None
    prior_swing_high: float | None
    prior_swing_low: float | None
    swings: list[Swing]
    fvgs: list[Zone]  # unmitigated, most recent first
    order_blocks: list[Zone]  # unmitigated, most recent first
    liquidity_sweep: str | None  # "high" | "low" | None
    bar_count: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "last_break": self.last_break,
            "swing_high": self.swing_high,
            "swing_low": self.swing_low,
            "prior_swing_high": self.prior_swing_high,
            "prior_swing_low": self.prior_swing_low,
            "fvgs": [
                {"kind": z.kind, "top": round(z.top, 4), "bottom": round(z.bottom, 4)}
                for z in self.fvgs[:3]
            ],
            "order_blocks": [
                {"kind": z.kind, "top": round(z.top, 4), "bottom": round(z.bottom, 4)}
                for z in self.order_blocks[:3]
            ],
            "liquidity_sweep": self.liquidity_sweep,
        }


def _empty(n: int, note: str) -> StructureReport:
    return StructureReport(
        trend="RANGE", last_break=None, last_break_index=None,
        swing_high=None, swing_low=None, prior_swing_high=None, prior_swing_low=None,
        swings=[], fvgs=[], order_blocks=[], liquidity_sweep=None, bar_count=n, notes=[note],
    )


def find_swings(highs: list[float], lows: list[float], *, left: int = 2, right: int = 2) -> list[Swing]:
    """Fractal pivots, oldest-first. A confirmed swing needs ``right`` bars
    after it, so the last ``right`` bars never produce one."""
    n = len(highs)
    out: list[Swing] = []
    for i in range(left, n - right):
        left_h = highs[i - left : i]
        right_h = highs[i + 1 : i + right + 1]
        left_l = lows[i - left : i]
        right_l = lows[i + 1 : i + right + 1]
        # strictly above everything to the left, at-least-equal to the right
        # (so a plateau's left edge is the pivot, and real-data ties don't hide it)
        if all(highs[i] > h for h in left_h) and all(highs[i] >= h for h in right_h):
            out.append(Swing(i, highs[i], "H"))
        if all(lows[i] < lo for lo in left_l) and all(lows[i] <= lo for lo in right_l):
            out.append(Swing(i, lows[i], "L"))
    out.sort(key=lambda s: s.index)
    return out


def _alternating(swings: list[Swing]) -> list[Swing]:
    """Collapse consecutive same-kind swings to the more extreme one, so the
    sequence strictly alternates H,L,H,L - the form the HH/HL test needs."""
    seq: list[Swing] = []
    for s in swings:
        if seq and seq[-1].kind == s.kind:
            if (s.kind == "H" and s.price >= seq[-1].price) or (s.kind == "L" and s.price <= seq[-1].price):
                seq[-1] = s
            continue
        seq.append(s)
    return seq


def _trend_from_swings(seq: list[Swing]) -> str:
    highs = [s.price for s in seq if s.kind == "H"][-2:]
    lows = [s.price for s in seq if s.kind == "L"][-2:]
    if len(highs) == 2 and len(lows) == 2:
        if highs[1] > highs[0] and lows[1] > lows[0]:
            return "UP"
        if highs[1] < highs[0] and lows[1] < lows[0]:
            return "DOWN"
    return "RANGE"


def _last_break(closes: list[float], seq: list[Swing], trend: str) -> tuple[str | None, int | None]:
    """Walk forward; the last bar that closes beyond the most recent
    opposing confirmed swing is the break. Classify BOS vs CHoCH by whether
    it agrees with ``trend``."""
    last: tuple[str | None, int | None] = (None, None)
    for i in range(1, len(closes)):
        prior = [s for s in seq if s.index < i]
        last_h = next((s for s in reversed(prior) if s.kind == "H"), None)
        last_l = next((s for s in reversed(prior) if s.kind == "L"), None)
        if last_h and closes[i] > last_h.price and closes[i - 1] <= last_h.price:
            kind = "BOS_UP" if trend == "UP" else "CHOCH_UP"
            last = (kind, i)
        if last_l and closes[i] < last_l.price and closes[i - 1] >= last_l.price:
            kind = "BOS_DOWN" if trend == "DOWN" else "CHOCH_DOWN"
            last = (kind, i)
    return last


def find_fvgs(
    highs: list[float], lows: list[float], *, max_age: int = 60
) -> list[Zone]:
    """Unmitigated 3-candle fair-value gaps, most recent first. ``max_age``
    caps how far back to look (bars)."""
    n = len(highs)
    zones: list[Zone] = []
    start = max(2, n - max_age)
    for i in range(start, n):
        # bullish: gap between bar i-2 high and bar i low
        if lows[i] > highs[i - 2]:
            top, bottom = lows[i], highs[i - 2]
            mitigated = any(lows[j] <= bottom for j in range(i + 1, n))
            if not mitigated and any(lows[j] < top for j in range(i + 1, n)):
                mitigated = False  # touched but not filled - still a live zone
            zones.append(Zone("bullish", top, bottom, i, mitigated))
        # bearish: gap between bar i-2 low and bar i high
        if highs[i] < lows[i - 2]:
            top, bottom = lows[i - 2], highs[i]
            mitigated = any(highs[j] >= top for j in range(i + 1, n))
            zones.append(Zone("bearish", top, bottom, i, mitigated))
    live = [z for z in zones if not z.mitigated]
    live.sort(key=lambda z: z.index, reverse=True)
    return live


def find_order_blocks(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float],
    seq: list[Swing], *, max_blocks: int = 4,
) -> list[Zone]:
    """The last opposing candle before an impulse that broke a swing.
    Bullish OB = last down-candle before an up-break; bearish OB = last
    up-candle before a down-break. Mitigated once price trades back into it."""
    n = len(closes)
    out: list[Zone] = []
    for i in range(2, n):
        prior = [s for s in seq if s.index < i]
        last_h = next((s for s in reversed(prior) if s.kind == "H"), None)
        last_l = next((s for s in reversed(prior) if s.kind == "L"), None)
        if last_h and closes[i] > last_h.price and closes[i - 1] <= last_h.price:
            k = next((j for j in range(i - 1, max(-1, i - 8), -1) if closes[j] < opens[j]), None)
            if k is not None:
                top, bottom = max(opens[k], closes[k]), lows[k]
                mit = any(lows[j] <= bottom for j in range(i + 1, n))
                out.append(Zone("bullish", top, bottom, k, mit))
        if last_l and closes[i] < last_l.price and closes[i - 1] >= last_l.price:
            k = next((j for j in range(i - 1, max(-1, i - 8), -1) if closes[j] > opens[j]), None)
            if k is not None:
                top, bottom = highs[k], min(opens[k], closes[k])
                mit = any(highs[j] >= top for j in range(i + 1, n))
                out.append(Zone("bearish", top, bottom, k, mit))
    live = [z for z in out if not z.mitigated]
    live.sort(key=lambda z: z.index, reverse=True)
    return live[:max_blocks]


def _liquidity_sweep(
    highs: list[float], lows: list[float], closes: list[float], *, lookback: int = 20, recent: int = 3
) -> str | None:
    n = len(closes)
    if n < lookback + recent:
        return None
    for i in range(n - recent, n):
        prior_high = max(highs[i - lookback : i])
        prior_low = min(lows[i - lookback : i])
        if highs[i] > prior_high and closes[i] < prior_high:
            return "high"
        if lows[i] < prior_low and closes[i] > prior_low:
            return "low"
    return None


def analyse(bars: list[dict[str, Any]], *, left: int = 2, right: int = 2, min_bars: int = 30) -> StructureReport:
    """``bars`` are ``{open,high,low,close,volume}`` dicts, oldest-first."""
    n = len(bars)
    if n < min_bars:
        return _empty(n, f"only {n} bars (< {min_bars})")
    opens = [float(b["open"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]

    swings = find_swings(highs, lows, left=left, right=right)
    seq = _alternating(swings)
    trend = _trend_from_swings(seq)
    brk, brk_i = _last_break(closes, seq, trend)

    hs = [s for s in seq if s.kind == "H"]
    ls = [s for s in seq if s.kind == "L"]
    return StructureReport(
        trend=trend,
        last_break=brk,
        last_break_index=brk_i,
        swing_high=hs[-1].price if hs else None,
        swing_low=ls[-1].price if ls else None,
        prior_swing_high=hs[-2].price if len(hs) > 1 else None,
        prior_swing_low=ls[-2].price if len(ls) > 1 else None,
        swings=seq,
        fvgs=find_fvgs(highs, lows),
        order_blocks=find_order_blocks(opens, highs, lows, closes, seq),
        liquidity_sweep=_liquidity_sweep(highs, lows, closes),
        bar_count=n,
        notes=[],
    )

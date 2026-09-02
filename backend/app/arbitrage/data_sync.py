"""Multi-instrument data synchronisation for the arbitrage backtest engine.

Two legs never tick at exactly the same instant. Before any spread / basis
maths runs, the engine aligns every leg onto a common timeline and records
how much fudging that took, so a result built on badly skewed data is
visibly flagged rather than silently wrong.

Modes (default for serious arbitrage = REJECT_STALE_DATA):

* STRICT_SYNC              — a timestamp is used only if every leg has a bar
                             at exactly that time.
* FORWARD_FILL_LIMITED     — carry a leg's last bar forward at most
                             ``max_fill`` steps.
* LAST_VALID_PRICE_WITH_MAX_AGE — carry forward while the carried bar is no
                             older than ``max_age_seconds``.
* REJECT_STALE_DATA        — like the max-age mode, but a timestamp where any
                             leg would be stale is dropped entirely and
                             counted as a stale-data event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.arbitrage.types import SyncMode
from app.strategies.base import Bar


def _to_epoch(ts: Any) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    s = str(ts).strip().replace("Z", "+00:00")
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0


@dataclass
class SyncedPoint:
    ts: Any
    bars: dict[str, Bar]           # instrument -> the bar used at this timestamp
    max_skew_seconds: float        # worst carry-forward age across legs here
    filled_legs: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    points: list[SyncedPoint]
    mode: SyncMode
    total_timeline: int
    used_points: int
    stale_events: int
    missing_events: int
    max_data_skew_seconds: float
    per_leg_bars: dict[str, int]

    @property
    def data_quality_score(self) -> float:
        if self.total_timeline == 0:
            return 0.0
        coverage = self.used_points / self.total_timeline
        skew_penalty = min(1.0, self.max_data_skew_seconds / 3600.0) * 0.3
        stale_penalty = min(1.0, self.stale_events / max(self.total_timeline, 1)) * 0.4
        return round(max(0.0, (coverage - skew_penalty - stale_penalty)) * 100.0, 1)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "total_timeline": self.total_timeline,
            "used_points": self.used_points,
            "stale_events": self.stale_events,
            "missing_events": self.missing_events,
            "max_data_skew_seconds": round(self.max_data_skew_seconds, 1),
            "data_quality_score": self.data_quality_score,
            "per_leg_bars": self.per_leg_bars,
        }


def synchronize(
    candles_by_instrument: dict[str, list[Bar]],
    *,
    mode: SyncMode = SyncMode.REJECT_STALE_DATA,
    max_age_seconds: float = 300.0,
    max_forward_fill: int = 1,
) -> SyncResult:
    legs = list(candles_by_instrument)
    idx: dict[str, list[tuple[float, Bar]]] = {
        s: sorted(((_to_epoch(b.timestamp), b) for b in bars), key=lambda x: x[0])
        for s, bars in candles_by_instrument.items()
    }
    timeline = sorted({e for series in idx.values() for e, _ in series})
    pos = dict.fromkeys(legs, 0)
    carried: dict[str, tuple[float, Bar] | None] = dict.fromkeys(legs, None)
    fill_count = dict.fromkeys(legs, 0)

    points: list[SyncedPoint] = []
    stale = missing = 0
    max_skew = 0.0

    for t in timeline:
        exact: dict[str, Bar] = {}
        used_bars: dict[str, Bar] = {}
        skew_here = 0.0
        filled: list[str] = []
        drop = False

        for s in legs:
            series = idx[s]
            while pos[s] < len(series) and series[pos[s]][0] <= t:
                carried[s] = series[pos[s]]
                fill_count[s] = 0
                pos[s] += 1
            cur = carried[s]
            if cur is not None and cur[0] == t:
                exact[s] = cur[1]
                used_bars[s] = cur[1]
                continue
            # not exact — decide by mode
            if mode is SyncMode.STRICT_SYNC or cur is None:
                drop = True
                break
            age = t - cur[0]
            fill_count[s] += 1
            if mode is SyncMode.FORWARD_FILL_LIMITED and fill_count[s] > max_forward_fill:
                drop = True
                break
            if (mode in (SyncMode.LAST_VALID_PRICE_WITH_MAX_AGE, SyncMode.REJECT_STALE_DATA)
                    and age > max_age_seconds):
                if mode is SyncMode.REJECT_STALE_DATA:
                    drop = True
                    break
                stale += 1  # LAST_VALID: allow but count it
            used_bars[s] = cur[1]
            filled.append(s)
            skew_here = max(skew_here, age)

        if drop:
            if len(exact) < len(legs):
                if any(fc > 0 for fc in fill_count.values()):
                    stale += 1
                else:
                    missing += 1
            continue
        max_skew = max(max_skew, skew_here)
        points.append(SyncedPoint(ts=t, bars=used_bars, max_skew_seconds=skew_here,
                                  filled_legs=filled))

    return SyncResult(
        points=points, mode=mode, total_timeline=len(timeline), used_points=len(points),
        stale_events=stale, missing_events=missing, max_data_skew_seconds=max_skew,
        per_leg_bars={s: len(bars) for s, bars in candles_by_instrument.items()},
    )

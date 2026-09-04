"""Pre-scoring eligibility screen for basket members.

Before a sleeve rule ranks its members, each candidate should clear a
data-quality + tradeability bar: enough price history, data that is not
stale or full of holes, a price above a penny-stock floor, and (when
volume is available) enough traded value to move size in and out.

Pure functions over bar lists (objects with ``.timestamp`` / ``.close`` /
optionally ``.volume``). No DB. ``screen_members`` is the entry point;
``app.baskets.service.screen_named_universe`` wires it to live candles for
the research / ops view. The rebalance engine emits these as *notes*
today (visibility) — a binding gate is opt-in via ``EligibilityGate``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from app.baskets.engine import _as_dt, _closes_upto


@dataclass(frozen=True)
class EligibilityGate:
    min_history_bars: int = 260          # ~1y of daily bars before as_of
    max_staleness_days: int = 20         # newest bar must be within this many calendar days
    max_internal_gap_days: int = 15      # no single hole bigger than this inside the series
    price_floor: float = 5.0             # last close must be at least this (penny-stock guard)
    min_median_turnover: float = 0.0     # median daily close*volume; 0 => skip the liquidity test
    lookback_bars: int = 0               # extra: require this many bars (e.g. the sleeve lookback)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_history_bars": self.min_history_bars,
            "max_staleness_days": self.max_staleness_days,
            "max_internal_gap_days": self.max_internal_gap_days,
            "price_floor": self.price_floor,
            "min_median_turnover": self.min_median_turnover,
            "lookback_bars": self.lookback_bars,
        }


DEFAULT_GATE = EligibilityGate()


@dataclass
class MemberEligibility:
    symbol: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)  # why NOT eligible (empty when eligible)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "eligible": self.eligible,
                "reasons": self.reasons, "stats": self.stats}


def _bar_dates(bars: list[Any], as_of: datetime) -> list[datetime]:
    out = [_as_dt(b.timestamp) for b in bars if _as_dt(b.timestamp) <= as_of]
    out.sort()
    return out


def assess_member(
    symbol: str,
    bars: list[Any] | None,
    as_of: datetime,
    *,
    gate: EligibilityGate = DEFAULT_GATE,
) -> MemberEligibility:
    reasons: list[str] = []
    stats: dict[str, Any] = {}

    if not bars:
        return MemberEligibility(symbol, False, ["no price history"], stats)

    dts = _bar_dates(bars, as_of)
    closes = _closes_upto(bars, as_of)
    stats["n_bars"] = len(dts)
    if not dts:
        return MemberEligibility(symbol, False, ["no bars at or before as_of"], stats)

    need = max(gate.min_history_bars, gate.lookback_bars + 5)
    if len(dts) < need:
        reasons.append(f"only {len(dts)} bars (need {need})")

    stale_days = (as_of - dts[-1]).days
    stats["staleness_days"] = stale_days
    if stale_days > gate.max_staleness_days:
        reasons.append(f"data stale by {stale_days}d (max {gate.max_staleness_days})")

    if len(dts) >= 2:
        gaps = [(dts[i] - dts[i - 1]).days for i in range(1, len(dts))]
        biggest = max(gaps)
        stats["max_gap_days"] = biggest
        if biggest > gate.max_internal_gap_days:
            reasons.append(f"internal data gap of {biggest}d (max {gate.max_internal_gap_days})")

    if closes:
        stats["last_close"] = round(closes[-1], 2)
        if closes[-1] < gate.price_floor:
            reasons.append(f"last close {closes[-1]:.2f} below floor {gate.price_floor}")

    if gate.min_median_turnover > 0:
        vals: list[float] = []
        for b in bars:
            if _as_dt(b.timestamp) > as_of:
                continue
            vol = float(getattr(b, "volume", 0) or 0)
            vals.append(float(b.close) * vol)
        recent = vals[-63:] if len(vals) >= 63 else vals
        med = median(recent) if recent else 0.0
        stats["median_turnover"] = round(med, 0)
        if med < gate.min_median_turnover:
            reasons.append(
                f"median turnover {med:,.0f} below {gate.min_median_turnover:,.0f}"
            )

    return MemberEligibility(symbol, not reasons, reasons, stats)


def screen_members(
    members: list[str],
    bars_by_symbol: dict[str, list[Any]],
    as_of: datetime,
    *,
    gate: EligibilityGate = DEFAULT_GATE,
) -> tuple[list[str], list[MemberEligibility]]:
    """-> (eligible symbols in input order, full per-member assessment list)."""
    assessed = [
        assess_member(m, bars_by_symbol.get(m), as_of, gate=gate) for m in members
    ]
    eligible = [a.symbol for a in assessed if a.eligible]
    return eligible, assessed

"""Shared value types for the Adaptive Options engine.

Every engine takes plain inputs (an option-chain snapshot, a list of
underlying bars, some history) and returns one of these frozen report
objects. They all expose ``as_dict()`` so the service layer can assemble a
single JSON payload without per-engine glue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --------------------------------------------------------------------------
# raw option-chain snapshot
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainRow:
    strike: float
    call_oi: float = 0.0
    put_oi: float = 0.0
    call_chg_oi: float = 0.0
    put_chg_oi: float = 0.0
    call_volume: float = 0.0
    put_volume: float = 0.0
    call_ltp: float | None = None
    put_ltp: float | None = None
    call_iv: float | None = None      # fraction
    put_iv: float | None = None       # fraction

    def as_dict(self) -> dict[str, Any]:
        return {
            "strike": self.strike,
            "call_oi": self.call_oi, "put_oi": self.put_oi,
            "call_chg_oi": self.call_chg_oi, "put_chg_oi": self.put_chg_oi,
            "call_volume": self.call_volume, "put_volume": self.put_volume,
            "call_ltp": self.call_ltp, "put_ltp": self.put_ltp,
            "call_iv": self.call_iv, "put_iv": self.put_iv,
        }


@dataclass(frozen=True)
class ChainSnapshot:
    underlying: str
    expiry: str                 # ISO date
    spot: float
    as_of: datetime
    dte: float                  # calendar days to expiry (fractional ok)
    rows: list[ChainRow]

    @property
    def t_years(self) -> float:
        return max(self.dte, 0.0) / 365.0

    def atm_strike(self) -> float | None:
        if not self.rows or self.spot <= 0:
            return None
        return min((r.strike for r in self.rows), key=lambda s: abs(s - self.spot))

    def strike_step(self) -> float:
        ks = sorted(r.strike for r in self.rows)
        gaps: dict[float, int] = {}
        for a, b in zip(ks, ks[1:], strict=False):
            g = round(b - a, 4)
            if g > 0:
                gaps[g] = gaps.get(g, 0) + 1
        return max(gaps, key=lambda k: gaps[k]) if gaps else 50.0

    def window(self, n: int) -> list[ChainRow]:
        """Rows within ``n`` strike-steps of ATM (all rows if n <= 0)."""
        atm = self.atm_strike()
        if atm is None or n <= 0:
            return list(self.rows)
        step = self.strike_step()
        return [r for r in self.rows if abs(r.strike - atm) <= n * step + 1e-6]

    def as_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying, "expiry": self.expiry, "spot": self.spot,
            "as_of": self.as_of.isoformat(), "dte": round(self.dte, 3),
            "atm": self.atm_strike(), "strike_step": self.strike_step(),
            "rows": [r.as_dict() for r in self.rows],
        }


# --------------------------------------------------------------------------
# engine outputs
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str               # INFO | WARNING | ERROR | CRITICAL
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass(frozen=True)
class ChainQualityReport:
    score: float                # 0-100
    ok: bool                    # False if any ERROR/CRITICAL — engines should not decide
    issues: list[QualityIssue]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "ok": self.ok,
            "issues": [i.as_dict() for i in self.issues],
            "blocking": [i.as_dict() for i in self.issues if i.severity in ("ERROR", "CRITICAL")],
        }


@dataclass(frozen=True)
class IntelReport:
    trend_direction: str        # UP | DOWN | SIDEWAYS
    trend_strength: float       # 0-100 (ADX-scaled)
    momentum: str               # RISING | FALLING | FLAT
    market_structure: str       # HH_HL | LH_LL | RANGE | COMPRESSION | EXPANSION | REVERSAL_UP | REVERSAL_DOWN
    vwap_distance_pct: float
    above_vwap: bool
    ema_stack: str              # BULLISH | BEARISH | MIXED
    rsi: float | None
    adx: float | None
    atr_pct: float | None
    bb_width_pctile: float | None
    rel_volume: float | None
    volume_trend: str           # EXPANDING | CONTRACTING | STABLE
    price_volume: str           # CONFIRMING | DIVERGING | NEUTRAL
    prev_day_high: float | None
    prev_day_low: float | None
    intraday_high: float | None
    intraday_low: float | None
    support: float | None
    resistance: float | None
    features: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class PCRSeriesStat:
    value: float
    zscore: float | None
    percentile: float | None    # 0-1 vs history
    slope: float | None         # per snapshot
    momentum: float | None      # recent change
    acceleration: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": round(self.value, 4),
            "zscore": None if self.zscore is None else round(self.zscore, 2),
            "percentile": None if self.percentile is None else round(self.percentile, 3),
            "slope": None if self.slope is None else round(self.slope, 5),
            "momentum": None if self.momentum is None else round(self.momentum, 4),
            "acceleration": None if self.acceleration is None else round(self.acceleration, 5),
        }


@dataclass(frozen=True)
class PCRState:
    oi_pcr: float
    volume_pcr: float
    chg_oi_pcr: float | None
    atm_pcr: float
    weighted_pcr: float
    near_atm_pcr: float
    state: str                  # STRONG_BEARISH..STRONG_BULLISH | EXTREME
    transition: str             # STABLE | TRANSITIONING_UP | TRANSITIONING_DOWN
    transition_confirmed: bool
    price_divergence: str       # ALIGNED | DIVERGING_BULLISH | DIVERGING_BEARISH | NA
    oi_pcr_stat: PCRSeriesStat
    weighted_stat: PCRSeriesStat
    history_len: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "oi_pcr": round(self.oi_pcr, 4),
            "volume_pcr": round(self.volume_pcr, 4),
            "chg_oi_pcr": None if self.chg_oi_pcr is None else round(self.chg_oi_pcr, 4),
            "atm_pcr": round(self.atm_pcr, 4),
            "near_atm_pcr": round(self.near_atm_pcr, 4),
            "weighted_pcr": round(self.weighted_pcr, 4),
            "state": self.state,
            "transition": self.transition,
            "transition_confirmed": self.transition_confirmed,
            "price_divergence": self.price_divergence,
            "oi_pcr_stat": self.oi_pcr_stat.as_dict(),
            "weighted_stat": self.weighted_stat.as_dict(),
            "history_len": self.history_len,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class OICluster:
    strike: float
    oi: float
    kind: str                   # CALL_WALL | PUT_WALL

    def as_dict(self) -> dict[str, Any]:
        return {"strike": self.strike, "oi": self.oi, "kind": self.kind}


@dataclass(frozen=True)
class PositioningReport:
    total_call_oi: float
    total_put_oi: float
    call_writing_strength: float     # 0-100 from ΔOI
    put_writing_strength: float
    call_unwinding: bool
    put_unwinding: bool
    price_oi_state: str              # LONG_BUILDUP | SHORT_BUILDUP | SHORT_COVERING | LONG_UNWINDING | MIXED
    put_support: float | None        # strike of the biggest put OI wall below spot
    call_resistance: float | None    # biggest call OI wall above spot
    oi_walls: list[OICluster]
    oi_concentration: float          # 0-1 (share of top-3 strikes)
    oi_migration: str                # UP | DOWN | STABLE | NA
    max_pain: float | None           # informational only
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_call_oi": self.total_call_oi, "total_put_oi": self.total_put_oi,
            "call_writing_strength": round(self.call_writing_strength, 1),
            "put_writing_strength": round(self.put_writing_strength, 1),
            "call_unwinding": self.call_unwinding, "put_unwinding": self.put_unwinding,
            "price_oi_state": self.price_oi_state,
            "put_support": self.put_support, "call_resistance": self.call_resistance,
            "oi_walls": [w.as_dict() for w in self.oi_walls],
            "oi_concentration": round(self.oi_concentration, 3),
            "oi_migration": self.oi_migration,
            "max_pain": self.max_pain,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class VolReport:
    atm_iv: float | None             # fraction
    call_iv: float | None
    put_iv: float | None
    iv_skew: float | None            # put_iv - call_iv, at ~equal-distance wings
    iv_rank: float | None            # 0-100 vs history
    iv_percentile: float | None      # 0-100 vs history
    iv_change: float | None          # vs previous snapshot
    realized_vol: float | None       # fraction, from underlying
    iv_minus_rv: float | None
    iv_class: str                    # LOW_IV | NORMAL_IV | HIGH_IV | EXTREME_IV | UNKNOWN
    term_structure: str              # CONTANGO | BACKWARDATION | FLAT | NA
    vol_selling_score: float         # 0-100 — higher = conditions favour premium selling
    vol_selling_verdict: str         # FAVOURABLE | NEUTRAL | UNFAVOURABLE
    history_len: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        r4 = lambda v: None if v is None else round(v, 4)  # noqa: E731
        r1 = lambda v: None if v is None else round(v, 1)  # noqa: E731
        return {
            "atm_iv": r4(self.atm_iv), "call_iv": r4(self.call_iv), "put_iv": r4(self.put_iv),
            "iv_skew": r4(self.iv_skew),
            "iv_rank": r1(self.iv_rank), "iv_percentile": r1(self.iv_percentile),
            "iv_change": r4(self.iv_change),
            "realized_vol": r4(self.realized_vol), "iv_minus_rv": r4(self.iv_minus_rv),
            "iv_class": self.iv_class, "term_structure": self.term_structure,
            "vol_selling_score": round(self.vol_selling_score, 1),
            "vol_selling_verdict": self.vol_selling_verdict,
            "history_len": self.history_len, "notes": self.notes,
        }


@dataclass(frozen=True)
class GreeksReport:
    atm_call: dict[str, float]
    atm_put: dict[str, float]
    per_strike: list[dict[str, Any]]     # strike + call/put greeks
    gamma_zone: tuple[float, float] | None  # strike band with the highest aggregate gamma
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "atm_call": self.atm_call, "atm_put": self.atm_put,
            "per_strike": self.per_strike,
            "gamma_zone": list(self.gamma_zone) if self.gamma_zone else None,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ExpectedMove:
    points: float | None
    upper: float | None
    lower: float | None
    pct: float | None
    by_method: dict[str, float | None]   # straddle | iv | atr
    current_move_points: float | None    # today's move so far
    current_vs_expected: float | None    # ratio
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "points": self.points, "upper": self.upper, "lower": self.lower, "pct": self.pct,
            "by_method": self.by_method,
            "current_move_points": self.current_move_points,
            "current_vs_expected": self.current_vs_expected,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ConfidenceScore:
    score: float                 # 0-100
    band: str                    # LOW | WEAK | MODERATE | HIGH | VERY_HIGH
    components: dict[str, float]  # component -> contribution
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1), "band": self.band,
            "components": {k: round(v, 1) for k, v in self.components.items()},
            "notes": self.notes,
        }


@dataclass(frozen=True)
class RegimeState:
    label: str                   # one of the 15 regimes
    direction: str               # BULLISH | BEARISH | NEUTRAL
    vol_class: str               # LOW | NORMAL | HIGH | EXTREME
    confidence: float            # 0-100
    stability: float             # 0-100
    transition_risk: float       # 0-100
    drivers: list[str]           # human-readable "why"
    contributing: dict[str, str] # input -> its reading

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "direction": self.direction, "vol_class": self.vol_class,
            "confidence": round(self.confidence, 1),
            "stability": round(self.stability, 1),
            "transition_risk": round(self.transition_risk, 1),
            "drivers": self.drivers, "contributing": self.contributing,
        }

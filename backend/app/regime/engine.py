"""5-state market regime classifier — pure functions over close series.

``classify(index_closes, vix_closes=None, member_closes=None)`` scores four
(optionally five) signals into a 0..100 "risk appetite" number and buckets
it:

    >= 78  strong_bull
    >= 60  bull
    >= 42  neutral
    >= 25  caution
    <  25  risk_off

Signals (each normalised to 0..1, higher = more risk-on):

  trend      px vs SMA50 / SMA200, SMA50 vs SMA200
  momentum   3-month and 6-month index return
  drawdown   distance below the trailing 1-year high
  volatility 21-day realised vol vs its own 1-year range (or absolute VIX)
  breadth    share of members above their own SMA200 (only if supplied)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

REGIMES = ("strong_bull", "bull", "neutral", "caution", "risk_off")
_YEAR = 252


@dataclass(frozen=True)
class RegimeState:
    regime: str
    score: float               # 0..100 risk-appetite
    drivers: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)  # sub-scores 0..1
    as_of: str | None = None

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "score": round(self.score, 1),
            "drivers": list(self.drivers),
            "signals": {k: round(v, 3) for k, v in self.signals.items()},
            "as_of": self.as_of,
        }


def _sma(xs: list[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if n > 0 and len(xs) >= n else None


def _roc(xs: list[float], n: int) -> float | None:
    if len(xs) <= n or xs[-n - 1] <= 0:
        return None
    return xs[-1] / xs[-n - 1] - 1.0


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _realised_vol(closes: list[float], win: int = 21) -> float | None:
    seg = closes[-(win + 1):]
    if len(seg) < 10:
        return None
    rets = [seg[i] / seg[i - 1] - 1.0 for i in range(1, len(seg)) if seg[i - 1] > 0]
    if len(rets) < 8:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(_YEAR)


def _trend_signal(c: list[float]) -> tuple[float, str]:
    ma50, ma200 = _sma(c, 50), _sma(c, 200)
    if ma50 is None or ma200 is None:
        # not enough history — lean on the shorter average only
        ma20 = _sma(c, 20)
        if ma20 is None:
            return 0.5, "trend: insufficient history"
        return (0.7 if c[-1] > ma20 else 0.3), "trend: short-MA only"
    checks = [c[-1] > ma50, c[-1] > ma200, ma50 > ma200]
    s = sum(checks) / 3.0
    label = ["below all averages", "mixed", "above key averages", "full uptrend"][sum(checks)]
    return s, f"trend: {label}"


def _momentum_signal(c: list[float]) -> tuple[float, str]:
    r3, r6 = _roc(c, 63), _roc(c, 126)
    parts = [r for r in (r3, r6) if r is not None]
    if not parts:
        return 0.5, "momentum: n/a"
    avg = sum(parts) / len(parts)
    # map -8%..+12% onto 0..1
    s = _clamp01((avg + 0.08) / 0.20)
    tag = "strong" if avg > 0.06 else "positive" if avg > 0 else "negative"
    return s, f"momentum: {tag} ({avg * 100:+.1f}%)"


def _drawdown_signal(c: list[float]) -> tuple[float, str]:
    win = c[-_YEAR:] if len(c) >= 60 else c
    if len(win) < 30:
        return 0.6, "drawdown: n/a"
    peak = max(win)
    dd = c[-1] / peak - 1.0 if peak > 0 else 0.0
    # 0% dd -> 1.0 ; -20% dd -> 0.0
    s = _clamp01(1.0 + dd / 0.20)
    return s, f"drawdown: {dd * 100:.1f}% from the 1-year high"


def _vol_signal(
    index_closes: list[float], vix_closes: list[float] | None
) -> tuple[float, str]:
    if vix_closes:
        v = vix_closes[-1]
        # VIX 11 -> calm (1.0), VIX 24 -> stressed (0.0)
        s = _clamp01((24.0 - v) / 13.0)
        return s, f"volatility: India VIX {v:.1f}"
    rv = _realised_vol(index_closes, 21)
    if rv is None:
        return 0.5, "volatility: n/a"
    hist = [
        _realised_vol(index_closes[: i + 1], 21)
        for i in range(len(index_closes) - _YEAR, len(index_closes), 5)
        if i > 30
    ]
    hist = sorted(h for h in hist if h is not None)
    if len(hist) >= 10:
        rank = sum(1 for h in hist if h <= rv) / len(hist)  # 0..1, higher = more vol
        s = 1.0 - rank
    else:
        s = _clamp01((0.22 - rv) / 0.14)  # absolute fallback: 8%..22%
    return s, f"volatility: realised {rv * 100:.0f}% annualised"


def _breadth_signal(member_closes: list[list[float]]) -> tuple[float, str] | None:
    ok = 0
    n = 0
    for c in member_closes:
        ma = _sma(c, 200)
        if ma is None:
            continue
        n += 1
        if c[-1] > ma:
            ok += 1
    if n < 10:
        return None
    s = ok / n
    return s, f"breadth: {ok}/{n} above their 200-day average"


_WEIGHTS = {"trend": 0.32, "momentum": 0.24, "drawdown": 0.20, "volatility": 0.16, "breadth": 0.08}


def classify(
    index_closes: list[float],
    *,
    vix_closes: list[float] | None = None,
    member_closes: list[list[float]] | None = None,
    as_of_label: str | None = None,
) -> RegimeState:
    if not index_closes or len(index_closes) < 30:
        return RegimeState("neutral", 50.0, ["insufficient index history"], {}, as_of_label)

    sig: dict[str, float] = {}
    drivers: list[str] = []
    for name, fn in (
        ("trend", lambda: _trend_signal(index_closes)),
        ("momentum", lambda: _momentum_signal(index_closes)),
        ("drawdown", lambda: _drawdown_signal(index_closes)),
        ("volatility", lambda: _vol_signal(index_closes, vix_closes)),
    ):
        s, why = fn()
        sig[name] = s
        drivers.append(why)

    weights = dict(_WEIGHTS)
    if member_closes:
        b = _breadth_signal(member_closes)
        if b is not None:
            sig["breadth"], why = b
            drivers.append(why)
    if "breadth" not in sig:
        weights.pop("breadth", None)

    wsum = sum(weights[k] for k in sig if k in weights) or 1.0
    score = 100.0 * sum(sig[k] * weights[k] for k in sig if k in weights) / wsum

    if score >= 78:
        regime = "strong_bull"
    elif score >= 60:
        regime = "bull"
    elif score >= 42:
        regime = "neutral"
    elif score >= 25:
        regime = "caution"
    else:
        regime = "risk_off"
    return RegimeState(regime, score, drivers, sig, as_of_label)


# --- consumers -----------------------------------------------------------

# target risk-asset exposure per regime, before the basket's own floor.
# caution deliberately sits close to the floor so a weak tape de-risks in
# the spirit of the old below-200-DMA gate; risk_off *is* the floor.
_EXPOSURE = {
    "strong_bull": 1.00,
    "bull": 1.00,
    "neutral": 0.85,
    "caution": 0.55,
    "risk_off": 0.00,  # -> the floor
}


def exposure_scale(regime: str, *, floor: float = 0.5, hard_cut: bool = False) -> float:
    """How much of a basket's risk-asset weight to keep in this regime.
    ``floor`` is the basket's own ``risk_off_scale``: the scale never drops
    below it, and ``risk_off`` collapses straight to it. With ``hard_cut``
    any non-bull regime drops straight to ``floor`` (for high-beta baskets
    that should not ride out pullbacks)."""
    floor = max(0.05, min(1.0, floor))
    if regime in ("strong_bull", "bull"):
        return 1.0
    if hard_cut or regime == "risk_off":
        return floor
    return max(_EXPOSURE.get(regime, 0.85), floor)


# additive deltas applied to (normalised) composite factor weights, then
# clamped >= 0 and renormalised. Only factors already in the profile move.
#
# Deliberately a light touch, and only in the extreme states: the
# graduated exposure scale already does the heavy de-risking, and an
# aggressive tilt that collapses the momentum weight in a drawdown was
# found to *deepen* drawdowns on the aggressive equity baskets. bull /
# neutral / caution keep the basket's configured weights.
_TILT: dict[str, dict[str, float]] = {
    "strong_bull": {"momentum": 0.05, "rs": 0.03, "growth": 0.03, "low_vol": -0.05},
    "bull": {},
    "neutral": {},
    "caution": {},
    "risk_off": {"low_vol": 0.08, "quality": 0.05, "momentum": -0.08, "growth": -0.03},
}


def factor_tilt(regime: str, weights: dict[str, float]) -> dict[str, float]:
    """Regime-adaptive reweighting of a composite factor profile."""
    delta = _TILT.get(regime) or {}
    if not delta or not weights:
        return dict(weights)
    out = {f: max(0.0, w + delta.get(f, 0.0)) for f, w in weights.items()}
    tot = sum(out.values())
    if tot <= 0:
        return dict(weights)
    return {f: w / tot for f, w in out.items()}

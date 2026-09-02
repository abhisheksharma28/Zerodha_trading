"""Multi-Factor Investing — rank a universe by a blended factor score.

Each rebalance the strategy scores every eligible instrument on several
*price-based* factors, standardises each factor cross-sectionally
(z-score across the eligible set, winsorised), blends them with
configurable weights into one composite, and targets a book of the
top-ranked names (optionally shorting the bottom).

Factors used (all causal, computed from the OHLCV stream — no external
data, no look-ahead):

* momentum        — blended skip-month return over 3 / 6 / 12 months
* low_volatility  — realised volatility (lower is better)
* trend_quality   — signed efficiency ratio: net move / path length,
                    rewarding smooth persistent up-trends
* liquidity       — average daily traded value (close x volume)

FUNDAMENTAL value and quality factors (P/E, P/B, ROE, ROCE, debt, earnings
growth) are deliberately NOT included: NSE point-in-time fundamentals are
not available, so using current fundamentals in a historical backtest
would be look-ahead bias. They are a documented future extension once a
point-in-time fundamentals source is wired in.

Not guaranteed profitable. Factor premia are regime-dependent and can be
absent or negative for years; validate out-of-sample and with realistic
turnover costs.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import rolling_volatility
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset

_FACTORS = ("momentum", "low_volatility", "trend_quality", "liquidity")


def _zscore(values: dict[str, float], clip: float) -> dict[str, float]:
    if not values:
        return {}
    xs = list(values.values())
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    sd = math.sqrt(var)
    if sd <= 0:
        return dict.fromkeys(values, 0.0)
    out: dict[str, float] = {}
    for k, x in values.items():
        z = (x - mean) / sd
        out[k] = max(-clip, min(clip, z))
    return out


class MultiFactorStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "multi-factor"
    NAME: ClassVar[str] = "Multi-Factor Investing"
    CATEGORY: ClassVar[str] = "Factor"
    MIN_INSTRUMENTS: ClassVar[int] = 5
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 275

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        # --- momentum factor ---
        "mom_lookback_short": ParamSpec("integer", 63, "Short momentum window (~3M).",
                                        min=5, max=500),
        "mom_lookback_mid": ParamSpec("integer", 126, "Mid momentum window (~6M).",
                                      min=10, max=750),
        "mom_lookback_long": ParamSpec("integer", 252, "Long momentum window (~12M).",
                                       min=20, max=1000),
        "mom_skip_recent": ParamSpec("integer", 21,
                                     "Bars skipped at the near end (12-1 style reversal guard).",
                                     min=0, max=60),
        "mom_blend_short": ParamSpec("number", 0.2, "Sub-weight on short momentum.", min=0.0, max=1.0),
        "mom_blend_mid": ParamSpec("number", 0.4, "Sub-weight on mid momentum.", min=0.0, max=1.0),
        "mom_blend_long": ParamSpec("number", 0.4, "Sub-weight on long momentum.", min=0.0, max=1.0),
        # --- other factor windows ---
        "volatility_lookback": ParamSpec("integer", 63, "Window for the low-volatility factor.",
                                         min=10, max=500),
        "trend_quality_lookback": ParamSpec("integer", 126, "Window for the trend-quality factor.",
                                            min=10, max=750),
        "liquidity_lookback": ParamSpec("integer", 21, "Window for the liquidity factor.",
                                        min=5, max=250),
        # --- composite weights (renormalised over the enabled factors) ---
        "weight_momentum": ParamSpec("number", 0.35, "Composite weight: momentum.", min=0.0, max=1.0),
        "weight_low_volatility": ParamSpec("number", 0.25, "Composite weight: low volatility.",
                                           min=0.0, max=1.0),
        "weight_trend_quality": ParamSpec("number", 0.25, "Composite weight: trend quality.",
                                          min=0.0, max=1.0),
        "weight_liquidity": ParamSpec("number", 0.15, "Composite weight: liquidity.",
                                      min=0.0, max=1.0),
        "winsor_z": ParamSpec("number", 3.0, "Clip each factor z-score to +/- this.",
                              min=1.0, max=10.0),
        # --- book construction ---
        "num_long_positions": ParamSpec("integer", 15, "Number of long positions.", min=1, max=200),
        "num_short_positions": ParamSpec("integer", 0, "Number of short positions.", min=0, max=200),
        "allow_short": ParamSpec("boolean", False, "Permit the short book (bottom-ranked names)."),
        "weighting": ParamSpec("enum", "equal_weight", "How book weight is split across names.",
                               choices=("equal_weight", "inverse_volatility", "score_weight")),
        "rebalance_frequency": ParamSpec("enum", "monthly", "Re-rank / rebalance cadence.",
                                         choices=("weekly", "monthly", "quarterly")),
        # --- eligibility filters ---
        "min_price": ParamSpec("number", 0.0, "Exclude instruments priced below this.",
                               min=0.0, group="filter"),
        "min_avg_turnover": ParamSpec("number", 0.0,
                                      "Exclude names whose avg daily traded value "
                                      "(close x volume) over liquidity_lookback is below this (INR).",
                                      min=0.0, group="filter"),
        "min_history_bars": ParamSpec("integer", 0,
                                      "Extra history required beyond the longest lookback.",
                                      min=0, max=2000, group="filter"),
        "max_volatility_pct": ParamSpec("number", 1000.0,
                                        "Exclude names whose per-bar realised vol (%) exceeds this.",
                                        min=0.0, max=5000.0, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            weight_momentum=0.25, weight_low_volatility=0.40, weight_trend_quality=0.20,
            weight_liquidity=0.15, num_long_positions=20, num_short_positions=0, allow_short=False,
            weighting="inverse_volatility", rebalance_frequency="monthly",
            min_avg_turnover=50_000_000.0, max_position_size_pct=10.0,
        ),
        "balanced": preset(
            weight_momentum=0.35, weight_low_volatility=0.25, weight_trend_quality=0.25,
            weight_liquidity=0.15, num_long_positions=15, num_short_positions=0, allow_short=False,
            weighting="equal_weight", rebalance_frequency="monthly",
            min_avg_turnover=25_000_000.0, max_position_size_pct=15.0,
        ),
        "aggressive": preset(
            weight_momentum=0.50, weight_low_volatility=0.10, weight_trend_quality=0.30,
            weight_liquidity=0.10, num_long_positions=10, num_short_positions=10, allow_short=True,
            weighting="score_weight", rebalance_frequency="weekly",
            min_avg_turnover=25_000_000.0, max_position_size_pct=20.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Scores a stock universe on blended price-based factors (momentum, low volatility, "
            "trend quality, liquidity), z-scores each factor across the universe, and holds a "
            "book of the highest composite scores, rebalanced on a fixed cadence."
        ),
        logic=(
            "At each rebalance, for every instrument with enough clean history compute: a "
            "skip-month blended 3/6/12-month return (momentum); realised volatility (low "
            "volatility, sign-flipped); a signed efficiency ratio = net move / path length "
            "(trend quality); average daily traded value (liquidity). Each factor is "
            "cross-sectionally z-scored and winsorised to +/- winsor_z, then blended with the "
            "configured weights (renormalised over enabled factors). Rank by composite; target "
            "the top num_long_positions long (and bottom num_short_positions short if "
            "allow_short), weighted equal / inverse-volatility / score-proportional. Eligibility "
            "uses only data available at the rebalance bar."
        ),
        timeframe="day (weekly / monthly / quarterly rebalance)",
        market_types=["NSE equity universes (NIFTY 100 / 200 / 500)"],
        supports_long=True, supports_short=True, supports_intraday=False, supports_swing=True,
        supports_market_neutral=True,
        complexity="High", time_horizon="Positional",
        risks=[
            "Factor premia are regime-dependent — a factor can underperform for years.",
            "Turnover and transaction costs erode the signal, especially at weekly cadence.",
            "Survivorship bias if today's universe is applied to the past.",
            "Price-based factors only; no fundamental value / quality until point-in-time "
            "fundamentals are available.",
        ],
        best_for="Diversified, positional equity books rebalanced monthly or quarterly.",
        warning="Factor strategies can underperform the index for extended periods.",
        required_data=[
            "Daily OHLCV for every instrument in the universe",
            "at least mom_lookback_long + mom_skip_recent + min_history_bars bars before the "
            "first rebalance",
        ],
        example=(
            "Universe of NIFTY 100 names, monthly rebalance, 15 equal-weight longs: on the first "
            "session of each month the 15 names with the highest blended factor z-score are held "
            "for the month. Mechanics only, not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._last_seen_date: date | None = None
        self._last_rebalance_date: date | None = None

    def on_bar(self, bar: Bar) -> None:
        d = self.bar_dt(bar).date()
        if (
            self._last_seen_date is not None
            and d != self._last_seen_date
            and self._rebalance_due(d)
        ):
            self._rebalance()
            self._last_rebalance_date = self._last_seen_date
        self._last_seen_date = d
        self.ingest(bar)

    # --- cadence ---------------------------------------------------

    def _rebalance_due(self, today: date) -> bool:
        if self._last_rebalance_date is None:
            return True
        last = self._last_rebalance_date
        freq = self.p["rebalance_frequency"]
        if freq == "weekly":
            return today.isocalendar()[:2] != last.isocalendar()[:2]
        if freq == "quarterly":
            return (today.year, (today.month - 1) // 3) != (last.year, (last.month - 1) // 3)
        return (today.year, today.month) != (last.year, last.month)

    # --- factor computation -------------------------------------

    def _longest_lookback(self) -> int:
        return max(
            int(self.p["mom_lookback_long"]) + int(self.p["mom_skip_recent"]),
            int(self.p["volatility_lookback"]),
            int(self.p["trend_quality_lookback"]),
            int(self.p["liquidity_lookback"]),
        )

    def _eligible(self, sym: str) -> bool:
        buf = self._buffers.get(sym)
        if buf is None:
            return False
        closes = list(buf.closes)
        need = self._longest_lookback() + 1 + int(self.p["min_history_bars"])
        if len(closes) < need or closes[-1] <= 0:
            return False
        if closes[-1] < float(self.p["min_price"]):
            return False
        liq_lb = int(self.p["liquidity_lookback"])
        if float(self.p["min_avg_turnover"]) > 0:
            vols = list(buf.volumes)[-liq_lb:]
            cl = closes[-liq_lb:]
            if not vols or (sum(c * v for c, v in zip(cl, vols, strict=False)) / len(vols)
                            < float(self.p["min_avg_turnover"])):
                return False
        rv = rolling_volatility(closes, int(self.p["volatility_lookback"]))
        return not (rv is not None and rv * 100.0 > float(self.p["max_volatility_pct"]))

    def _raw_factors(self, sym: str) -> dict[str, float] | None:
        buf = self._buffers[sym]
        closes = list(buf.closes)
        vols = list(buf.volumes)

        skip = int(self.p["mom_skip_recent"])
        anchor = -1 - skip  # last usable close for momentum (skip the recent window)
        mom_parts: list[float] = []
        for lb, w in (
            (int(self.p["mom_lookback_short"]), float(self.p["mom_blend_short"])),
            (int(self.p["mom_lookback_mid"]), float(self.p["mom_blend_mid"])),
            (int(self.p["mom_lookback_long"]), float(self.p["mom_blend_long"])),
        ):
            base_i = anchor - lb
            if w == 0 or -base_i > len(closes) or closes[base_i] <= 0:
                continue
            mom_parts.append(w * (closes[anchor] / closes[base_i] - 1.0))
        if not mom_parts:
            return None
        momentum = sum(mom_parts)

        rv = rolling_volatility(closes, int(self.p["volatility_lookback"]))
        if rv is None:
            return None
        low_volatility = -rv  # lower vol -> higher factor

        tq_lb = int(self.p["trend_quality_lookback"])
        seg = closes[-tq_lb - 1:]
        path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
        trend_quality = ((seg[-1] - seg[0]) / path) if path > 0 else 0.0

        liq_lb = int(self.p["liquidity_lookback"])
        cl, vl = closes[-liq_lb:], vols[-liq_lb:]
        turnover = sum(c * v for c, v in zip(cl, vl, strict=False)) / max(1, len(vl))
        liquidity = math.log1p(max(0.0, turnover))

        return {
            "momentum": momentum,
            "low_volatility": low_volatility,
            "trend_quality": trend_quality,
            "liquidity": liquidity,
        }

    def _composite_scores(self, raw: dict[str, dict[str, float]]) -> dict[str, float]:
        weights = {
            "momentum": float(self.p["weight_momentum"]),
            "low_volatility": float(self.p["weight_low_volatility"]),
            "trend_quality": float(self.p["weight_trend_quality"]),
            "liquidity": float(self.p["weight_liquidity"]),
        }
        enabled = {f: w for f, w in weights.items() if w > 0}
        total_w = sum(enabled.values()) or 1.0
        clip = float(self.p["winsor_z"])

        zbyf: dict[str, dict[str, float]] = {}
        for f in enabled:
            zbyf[f] = _zscore({s: v[f] for s, v in raw.items() if f in v}, clip)

        scores: dict[str, float] = {}
        for sym in raw:
            scores[sym] = sum(
                (w / total_w) * zbyf[f].get(sym, 0.0) for f, w in enabled.items()
            )
        return scores

    # --- rebalance ----------------------------------------------

    def _rebalance(self) -> None:
        raw: dict[str, dict[str, float]] = {}
        for sym in self._buffers:
            if not self._eligible(sym):
                continue
            rf = self._raw_factors(sym)
            if rf is not None:
                raw[sym] = rf
        if len(raw) < 2:
            return

        scores = self._composite_scores(raw)
        ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
        n_long = min(int(self.p["num_long_positions"]), len(ranked))
        longs = ranked[:n_long]
        shorts: list[str] = []
        if self.p["allow_short"] and int(self.p["num_short_positions"]) > 0:
            n_short = min(int(self.p["num_short_positions"]), max(0, len(ranked) - n_long))
            shorts = ranked[len(ranked) - n_short:] if n_short else []

        capital = float(self.p["capital_allocation"])
        targets: dict[str, int] = {}
        self._fill_side(targets, longs, capital, raw, scores, sign=1)
        self._fill_side(targets, shorts, capital, raw, scores, sign=-1)

        for sym, held in list(self.context.positions.items()):
            if held != 0 and sym not in targets:
                targets[sym] = 0
        for sym, target_qty in targets.items():
            self.rebalance_to(sym, target_qty, exchange=self.p["exchange"],
                              product=self.p["product"])

    def _fill_side(
        self, targets: dict[str, int], names: list[str], capital: float,
        raw: dict[str, dict[str, float]], scores: dict[str, float], *, sign: int,
    ) -> None:
        if not names:
            return
        method = self.p["weighting"]
        if method == "inverse_volatility":
            inv = {s: (1.0 / -raw[s]["low_volatility"]) if raw[s]["low_volatility"] < 0 else 0.0
                   for s in names}
            tot = sum(inv.values())
            weights = {s: (inv[s] / tot if tot > 0 else 1.0 / len(names)) for s in names}
        elif method == "score_weight":
            lo = min(scores[s] for s in names)
            shifted = {s: max(1e-6, scores[s] - lo + 1e-6) for s in names}
            tot = sum(shifted.values())
            weights = {s: shifted[s] / tot for s in names}
        else:  # equal_weight
            weights = dict.fromkeys(names, 1.0 / len(names))

        for sym in names:
            px = self._buffers[sym].closes[-1]
            if px <= 0:
                continue
            alloc = capital * weights[sym]
            qty = min(int(alloc // px), self._max_position_qty(px, capital))
            if qty > 0:
                targets[sym] = sign * qty

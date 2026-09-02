"""Chinese Transformer — cross-sectional AI stock selection.

Inspired by Zhang et al., "From Attention to Profit" (arXiv:2404.00424):
rank the whole universe every rebalance and hold the strongest names,
rather than predicting any single stock's direction.

This *template* is the deployable, zero-training form of the system. It
scores each eligible name with a transparent, standardized multi-factor
composite (cross-sectional z-scores of momentum, low-volatility, trend
quality and liquidity factors), ranks, and holds an equal-weight book of
the top N with rank hysteresis and a minimum holding period so it does not
churn. The heavier research pipeline (``app.chinese_transformer``) — data-
quality gate, full feature panel, walk-forward-validated ridge / gradient-
boosted rankers, Rank-IC reporting — sits behind the strategy API and can
supply the scores here once it clears out-of-sample validation.

Not guaranteed profitable. Cross-sectional models suffer fast drawdowns in
violent style reversals ("momentum crashes"). The universe is today's
index membership, so historical runs carry survivorship bias. Validate
out-of-sample with realistic turnover costs before any live use.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import numpy as np

from app.chinese_transformer.features import raw_features
from app.strategies.base import Bar
from app.strategies.library.base import (
    ParamSpec,
    TemplateMetadata,
    TemplateStrategy,
    preset,
)

_SLUG = "chinese-transformer"

# raw feature -> (composite bucket, sign). Lower vol / lower illiquidity are good.
_FACTOR_MAP: dict[str, tuple[str, float]] = {
    "ret_20": ("momentum", 1.0),
    "ret_60": ("momentum", 1.0),
    "ret_120": ("momentum", 1.0),
    "mom_accel": ("momentum", 0.5),
    "dist_sma50": ("trend", 1.0),
    "dist_52w_high": ("trend", 1.0),
    "adx_14": ("trend", 0.5),
    "vol_60": ("low_vol", -1.0),
    "max_dd_120": ("low_vol", 1.0),      # max_dd_120 is negative; less-negative = better
    "downside_dev_20": ("low_vol", -1.0),
    "amihud_20": ("liquidity", -1.0),
    "rel_volume_20": ("liquidity", 0.5),
    "ret_1": ("reversal_guard", -1.0),   # don't chase 1-day pops
}


def _zscore(v: np.ndarray) -> np.ndarray:
    s = v.std()
    return np.zeros_like(v) if s < 1e-12 else np.clip((v - v.mean()) / s, -4.0, 4.0)


class ChineseTransformerStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = _SLUG
    NAME: ClassVar[str] = "Chinese Transformer"
    CATEGORY: ClassVar[str] = "AI / Cross-Sectional"
    MIN_INSTRUMENTS: ClassVar[int] = 10
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 260

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "num_positions": ParamSpec("integer", 10, "Names held equal-weight.", min=2, max=100),
        "rebalance_frequency": ParamSpec("enum", "weekly", "Re-rank cadence.",
                                         choices=("daily", "weekly", "monthly")),
        "rank_hysteresis": ParamSpec("integer", 5,
                                     "Keep a held name until it falls below "
                                     "num_positions + this in the ranking.", min=0, max=100),
        "min_holding_days": ParamSpec("integer", 5, "Do not exit a name before this many days.",
                                      min=0, max=250),
        "w_momentum": ParamSpec("number", 1.0, "Weight on the momentum factor.", min=0.0, max=5.0),
        "w_trend": ParamSpec("number", 0.6, "Weight on trend-quality factor.", min=0.0, max=5.0),
        "w_low_vol": ParamSpec("number", 0.5, "Weight on the low-volatility factor.",
                               min=0.0, max=5.0),
        "w_liquidity": ParamSpec("number", 0.3, "Weight on the liquidity factor.",
                                 min=0.0, max=5.0),
        "w_reversal_guard": ParamSpec("number", 0.3, "Penalty on 1-day return spikes.",
                                      min=0.0, max=5.0),
        "min_price": ParamSpec("number", 20.0, "Exclude names priced below this.",
                               min=0.0, group="filter"),
        "min_avg_daily_value": ParamSpec("number", 5.0e7,
                                         "Exclude names with 20-bar average traded value below "
                                         "this (INR).", min=0.0, group="filter"),
        "min_history_bars": ParamSpec("integer", 200, "Clean bars required before a name is "
                                      "eligible.", min=60, max=1000, group="filter"),
        "regime_exposure_scaling": ParamSpec("boolean", True,
                                             "Hold fewer names when the benchmark is below its "
                                             "trend SMA.", group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            num_positions=15, rebalance_frequency="monthly", rank_hysteresis=8,
            min_holding_days=20, w_momentum=0.8, w_trend=0.6, w_low_vol=0.9, w_liquidity=0.4,
            w_reversal_guard=0.4, min_avg_daily_value=1.0e8, max_position_size_pct=12.0,
            regime_filter_enabled=True, regime_exposure_scaling=True,
        ),
        "balanced": preset(
            num_positions=10, rebalance_frequency="weekly", rank_hysteresis=5, min_holding_days=5,
            w_momentum=1.0, w_trend=0.6, w_low_vol=0.5, w_liquidity=0.3, w_reversal_guard=0.3,
            min_avg_daily_value=5.0e7, max_position_size_pct=15.0, regime_exposure_scaling=True,
        ),
        "aggressive": preset(
            num_positions=6, rebalance_frequency="weekly", rank_hysteresis=3, min_holding_days=2,
            w_momentum=1.4, w_trend=0.7, w_low_vol=0.2, w_liquidity=0.2, w_reversal_guard=0.2,
            min_avg_daily_value=2.5e7, max_position_size_pct=25.0, regime_exposure_scaling=False,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=_SLUG, name="Chinese Transformer", category="AI / Cross-Sectional",
        description=(
            "Ranks the whole NSE universe every rebalance by a standardized multi-factor alpha "
            "composite and holds an equal-weight book of the top N, with rank hysteresis and a "
            "minimum holding period to control turnover."
        ),
        logic=(
            "At each rebalance, for every name with enough clean history compute raw price/"
            "momentum, volatility, trend-quality and liquidity features from causal bars, "
            "cross-sectionally z-score them, and blend into momentum / trend / low_vol / "
            "liquidity / reversal-guard buckets with the configured weights. Rank by the total "
            "score. Target the top num_positions equal-weight; a held name is kept until it "
            "falls below num_positions + rank_hysteresis or until min_holding_days lets it go. "
            "If regime_exposure_scaling is on and the benchmark is below its trend SMA, hold "
            "fewer names. Eligibility and scoring use only data up to the rebalance bar."
        ),
        timeframe="day (weekly / monthly rebalance typical)",
        market_types=["NSE equity universes (NIFTY 100 / 200)"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="High", time_horizon="Positional",
        risks=[
            "Style/momentum crashes: fast, deep drawdowns when leadership violently reverses.",
            "Turnover costs erode the signal, especially at daily cadence.",
            "Survivorship bias: the universe is today's constituents applied to the past.",
            "The shipped scorer is a transparent factor composite, not a trained Transformer.",
        ],
        best_for="Positional, diversified NSE equity books rebalanced weekly or monthly.",
        warning="Cross-sectional alpha models can suffer sharp drawdowns during style reversals.",
        required_data=[
            "Daily OHLCV for every instrument in the universe",
            "at least ~260 bars before the first rebalance",
            "benchmark bars in the stream if regime scaling / filter is on",
        ],
        example=(
            "NIFTY 100 universe, weekly rebalance, 10 longs: each Monday the 10 names with the "
            "highest blended momentum / trend / low-vol / liquidity score are held equal-weight, "
            "names only dropped once they fall out of the top 15. Mechanics only, not a "
            "performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._last_seen_date: date | None = None
        self._last_rebalance_date: date | None = None
        self._entry_date: dict[str, date] = {}

    # --- bar plumbing -------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        d = self.bar_dt(bar).date()
        if (
            self._last_seen_date is not None
            and d != self._last_seen_date
            and self._rebalance_due(d)
        ):
            self._rebalance(self._last_seen_date)
            self._last_rebalance_date = self._last_seen_date
        self._last_seen_date = d
        self.ingest(bar)

    def _rebalance_due(self, today: date) -> bool:
        if self._last_rebalance_date is None:
            return True
        freq = self.p["rebalance_frequency"]
        last = self._last_rebalance_date
        if freq == "daily":
            return today > last
        if freq == "weekly":
            return today.isocalendar()[:2] != last.isocalendar()[:2]
        return (today.year, today.month) != (last.year, last.month)

    # --- scoring ----------------------------------------------------

    def _eligible_raw(self, sym: str) -> dict[str, float] | None:
        buf = self._buffers.get(sym)
        if buf is None or len(buf.closes) < int(self.p["min_history_bars"]):
            return None
        closes = list(buf.closes)
        if closes[-1] < float(self.p["min_price"]):
            return None
        vols = list(buf.volumes)
        recent = list(zip(closes[-20:], vols[-20:], strict=False))
        if recent:
            adv = sum(c * v for c, v in recent) / len(recent)
            if adv < float(self.p["min_avg_daily_value"]):
                return None
        return raw_features(
            np.asarray(closes), np.asarray(list(buf.highs)),
            np.asarray(list(buf.lows)), np.asarray(vols),
        )

    def _score(self, raw_by_symbol: dict[str, dict[str, float]]) -> dict[str, float]:
        syms = list(raw_by_symbol)
        weights = {
            "momentum": float(self.p["w_momentum"]),
            "trend": float(self.p["w_trend"]),
            "low_vol": float(self.p["w_low_vol"]),
            "liquidity": float(self.p["w_liquidity"]),
            "reversal_guard": float(self.p["w_reversal_guard"]),
        }
        bucket_scores: dict[str, np.ndarray] = {b: np.zeros(len(syms)) for b in weights}
        bucket_terms: dict[str, int] = dict.fromkeys(weights, 0)
        for feat, (bucket, sign) in _FACTOR_MAP.items():
            vals = np.array([raw_by_symbol[s].get(feat, 0.0) for s in syms], dtype=float)
            bucket_scores[bucket] = bucket_scores[bucket] + sign * _zscore(vals)
            bucket_terms[bucket] += 1
        total = np.zeros(len(syms))
        for b, w in weights.items():
            if bucket_terms[b]:
                total = total + w * (bucket_scores[b] / bucket_terms[b])
        return dict(zip(syms, total.tolist(), strict=True))

    # --- rebalance ------------------------------------------------

    def _rebalance(self, as_of: date) -> None:
        bench = self.p["regime_benchmark"]
        raw_by_symbol: dict[str, dict[str, float]] = {}
        for sym in self._buffers:
            if sym == bench:
                continue
            r = self._eligible_raw(sym)
            if r is not None:
                raw_by_symbol[sym] = r
        if len(raw_by_symbol) < self.MIN_INSTRUMENTS:
            return

        scores = self._score(raw_by_symbol)
        ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
        rank_of = {s: i for i, s in enumerate(ranked)}

        n_target = int(self.p["num_positions"])
        if self.p["regime_exposure_scaling"] and not self.long_entries_allowed():
            n_target = max(2, n_target // 2)
        n_target = min(n_target, len(ranked))
        keep_cutoff = n_target + int(self.p["rank_hysteresis"])

        target: set[str] = set(ranked[:n_target])
        for sym, held in self.context.positions.items():
            if held <= 0 or sym not in rank_of:
                continue
            held_days = (as_of - self._entry_date.get(sym, as_of)).days
            if held_days < int(self.p["min_holding_days"]) or rank_of[sym] < keep_cutoff:
                target.add(sym)

        capital = float(self.p["capital_allocation"])
        longs = [s for s in ranked if s in target][: max(n_target, len(target))]
        if not longs:
            return
        per_name = capital / len(longs)
        targets: dict[str, int] = {}
        for sym in longs:
            px = self._buffers[sym].closes[-1]
            if px <= 0:
                continue
            qty = min(int(per_name // px), self._max_position_qty(px, capital))
            targets[sym] = max(0, qty)

        for sym, held in list(self.context.positions.items()):
            if held != 0 and sym not in targets:
                targets[sym] = 0

        for sym, qty in targets.items():
            prev = self.position(sym)
            self.rebalance_to(sym, qty, exchange=self.p["exchange"], product=self.p["product"])
            if qty > 0 and prev <= 0:
                self._entry_date[sym] = as_of
            elif qty == 0:
                self._entry_date.pop(sym, None)

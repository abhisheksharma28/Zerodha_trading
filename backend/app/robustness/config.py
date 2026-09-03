"""Per-strategy robustness knobs.

``SWEEP[slug]`` = (parameter, [values]) for the sensitivity check. The
preset's own value for that parameter is added to the grid automatically.
Universe / window / preset come from ``app.leaderboard.config.CANONICAL``.
"""

from __future__ import annotations

WF_FOLDS = 4
WF_OOS_FRACTION = 0.5  # rear half of the span is split into the OOS folds
MC_SIMS = 3000

SWEEP: dict[str, tuple[str, list[float]] | None] = {
    "cross-sectional-momentum": ("lookback_2", [30, 45, 60, 90, 120, 180]),
    "trend-following": ("slow_period", [30, 50, 80, 120, 160, 200]),
    "donchian-breakout": ("entry_period", [15, 20, 25, 30, 40, 55]),
    "mean-reversion": ("entry_zscore", [1.5, 2.0, 2.5, 3.0, 3.5]),
    "multi-factor": ("weight_momentum", [0.15, 0.25, 0.35, 0.50, 0.65]),
    "weapon-candle": ("arm_expiry_bars", [1, 2, 3, 5, 8]),
    "volatility-regime": ("trend_ma_period", [20, 35, 50, 75, 100]),
    "regime-adaptive": ("adx_trend_min", [18, 22, 25, 30, 35]),
    "supertrend": ("multiplier", [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]),
    "golden-cross": ("slow_period", [100, 150, 200, 250, 300]),
    "rsi2-reversion": ("entry_rsi", [5, 10, 15, 20, 25]),
    "bollinger-reversion": ("bb_stdev", [1.5, 2.0, 2.5, 3.0]),
    "fiftytwo-week-high": ("band_pct", [1.0, 2.0, 3.0, 5.0, 8.0]),
    "dual-momentum": ("lookback", [63, 126, 189, 252]),
    # intraday templates: MC + walk-forward only (5m sweeps are too slow)
    "opening-range-breakout": None,
    "opening-breakout-us": None,
}


def sweep_for(slug: str) -> tuple[str, list[float]] | None:
    return SWEEP.get(slug)

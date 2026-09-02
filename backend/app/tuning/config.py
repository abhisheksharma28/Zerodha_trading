"""Per-strategy tuning grid — two parameters, kept small on purpose.

Values are chosen to bracket the preset with sensible NSE ranges, not to
data-mine. ``run_tuning`` always adds the preset's own value for each
parameter to the grid so the preset is a candidate.
"""

from __future__ import annotations

TUNING_GRID: dict[str, dict[str, list]] = {
    "cross-sectional-momentum": {
        "lookback_2": [30, 60, 90, 120],
        "rebalance_frequency": ["weekly", "monthly"],
    },
    "trend-following": {
        "slow_period": [30, 50, 80, 120],
        "trend_strength_min_pct": [0.0, 0.5, 1.0],
    },
    "donchian-breakout": {
        "entry_period": [15, 20, 30, 45],
        "atr_stop_mult": [1.5, 2.0, 3.0],
    },
    "mean-reversion": {
        "lookback": [15, 20, 30, 40],
        "entry_zscore": [1.5, 2.0, 2.5, 3.0],
    },
    "multi-factor": {
        "num_long_positions": [10, 15, 25],
        "rebalance_frequency": ["weekly", "monthly", "quarterly"],
    },
    "weapon-candle": {
        "mode": ["classic", "enhanced"],
        "arm_expiry_bars": [2, 3, 5],
    },
    "volatility-regime": {
        "mode": ["breakout_and_trend", "trend_only", "breakout_only"],
        "trend_ma_period": [30, 50, 100],
    },
    "regime-adaptive": {
        "adx_trend_min": [20, 25, 30],
        "er_trend_min": [0.25, 0.35, 0.45],
    },
    # intraday templates excluded — 5-minute grid runs are too slow.
}

# Minimum out-of-sample closed trades for a grid point to be eligible.
MIN_OOS_TRADES = 5
# The tuned combo must beat the preset's worst-half Sharpe by at least this.
MIN_SHARPE_EDGE = 0.15
# Fraction of the window used for in-sample (rest is out-of-sample).
IN_SAMPLE_FRAC = 0.6


def grid_for(slug: str) -> dict[str, list] | None:
    return TUNING_GRID.get(slug)

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
    "supertrend": {
        "multiplier": [2.0, 3.0, 4.0],
        "atr_period": [7, 10, 14],
    },
    "golden-cross": {
        "slow_period": [100, 150, 200],
        "ma_type": ["sma", "ema"],
    },
    "rsi2-reversion": {
        "entry_rsi": [5, 10, 15],
        "regime_window": [100, 150, 200],
    },
    "bollinger-reversion": {
        "bb_stdev": [1.8, 2.0, 2.5],
        "regime_window": [0, 100, 200],
    },
    "fiftytwo-week-high": {
        "band_pct": [2.0, 3.0, 5.0],
        "exit_pct": [8.0, 12.0, 15.0],
    },
    "dual-momentum": {
        "lookback": [126, 189, 252],
        "top_n": [2, 3, 5],
    },
    "low-volatility-anomaly": {
        "vol_lookback": [90, 120, 180],
        "hold_n": [10, 15, 20],
    },
    "sector-momentum-rotation": {
        "mom_lookback": [63, 126, 252],
        "hold_n": [2, 3, 4],
    },
    "pairs-trading": {
        "entry_zscore": [1.5, 2.0, 2.5],
        "lookback": [40, 60, 90],
    },
    "ttm-squeeze": {
        "kc_mult": [1.0, 1.5, 2.0],
        "mom_period": [12, 20, 30],
    },
    "turn-of-month": {
        "enter_dom": [24, 26, 28],
        "exit_dom": [3, 4, 5],
    },
    "rs-line-high": {
        "rs_lookback": [63, 126, 189],
        "price_band_pct": [5.0, 8.0, 12.0],
    },
    "volatility-contraction-breakout": {
        "contraction_window": [18, 25, 35],
        "target_r": [2.0, 2.5, 3.0],
    },
    "seasonal-sector-rotation": {
        "hold_n": [2, 3, 4],
        "metric": ["mean_pct", "median_pct"],
    },
    "seasonal-sector-stock-rotation": {
        "top_sectors": [2, 3],
        "hold_n": [6, 8, 12],
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

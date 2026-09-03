"""Starter basket definitions — a small, opinionated set the user can
clone and edit. Each is a valid ``spec`` (see ``app.baskets.spec``)."""

from __future__ import annotations

from typing import Any

_LARGE_CAPS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "LT", "ITC", "AXISBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "NTPC", "POWERGRID", "TATAMOTORS",
]

_SECTOR_BELLWETHERS = [
    "HDFCBANK", "INFY", "RELIANCE", "SUNPHARMA", "MARUTI", "TATASTEEL",
    "HINDUNILVR", "LT", "DLF", "BHARTIARTL",
]

TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "all-weather",
        "name": "All-Weather (Equity / Gold / Silver)",
        "description": (
            "A static 50 / 30 / 20 split across a Nifty index ETF, gold and silver — "
            "the precious-metals sleeves are the ballast that cushions equity drawdowns. "
            "No rotation; rebalanced monthly back to the fixed weights."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "equity", "name": "Equity (Nifty ETF)", "weight_pct": 50.0,
                 "weighting": "equal", "members": ["NIFTYBEES"], "rule": {"type": "none"}},
                {"id": "gold", "name": "Gold", "weight_pct": 30.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": {"type": "none"}},
                {"id": "silver", "name": "Silver", "weight_pct": 20.0,
                 "weighting": "equal", "members": ["SILVERBEES"], "rule": {"type": "none"}},
            ]
        },
    },
    {
        "key": "momentum-gold-ballast",
        "name": "Momentum core + Gold ballast",
        "description": (
            "A 65% equity sleeve that each month holds the 8 strongest large caps "
            "(6-month momentum, must be above its 200-day average), balanced by a "
            "25% gold + 10% silver ballast. Inverse-volatility weighted inside the "
            "equity sleeve so no single name dominates."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "equity-core", "name": "Momentum core", "weight_pct": 65.0,
                 "weighting": "inverse_vol", "members": _LARGE_CAPS,
                 "rule": {"type": "momentum_top_k", "lookback": 126, "top_k": 8,
                          "trend_ma": 200, "min_roc_pct": 0.0}},
                {"id": "gold", "name": "Gold", "weight_pct": 25.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": {"type": "none"}},
                {"id": "silver", "name": "Silver", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["SILVERBEES"], "rule": {"type": "none"}},
            ]
        },
    },
    {
        "key": "sector-leaders-gold",
        "name": "Sector leaders + Gold",
        "description": (
            "Rotates quarterly into the 5 strongest sector bellwethers (one liquid "
            "name per major sector, 6-month momentum, above the 200-day average), "
            "equal-weighted, with a 20% gold sleeve for balance."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "sector-leaders", "name": "Sector leaders", "weight_pct": 80.0,
                 "weighting": "equal", "members": _SECTOR_BELLWETHERS,
                 "rule": {"type": "momentum_top_k", "lookback": 126, "top_k": 5,
                          "trend_ma": 200, "min_roc_pct": 0.0}},
                {"id": "gold", "name": "Gold", "weight_pct": 20.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": {"type": "none"}},
            ]
        },
    },
]


def templates() -> list[dict[str, Any]]:
    return [dict(t) for t in TEMPLATES]

"""Shared market-regime engine.

A single 5-state classifier (`strong_bull` / `bull` / `neutral` / `caution`
/ `risk_off`) computed causally from an index close series (plus optional
India VIX and breadth). Consumed by the basket rebalance engine for
graduated exposure + regime-adaptive factor weights, and exposed at
``GET /market/regime``.

Kept price-only-first so it works inside a walk-forward backtest with no
look-ahead.
"""

from app.regime.engine import (
    REGIMES,
    RegimeState,
    classify,
    exposure_scale,
    factor_tilt,
)

__all__ = [
    "REGIMES",
    "RegimeState",
    "classify",
    "exposure_scale",
    "factor_tilt",
]

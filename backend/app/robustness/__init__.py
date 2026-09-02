"""Robustness layer for the strategy leaderboard.

For a strategy's canonical config it runs three checks and caches the
result next to the canonical backtest:

* Monte Carlo on the realised per-trade P&L (luck / path-dependence).
* Walk-forward: rolling in-sample / out-of-sample folds with the fixed
  preset, to measure performance decay out-of-sample.
* Parameter sensitivity: sweep one key parameter and decide whether the
  preset sits on a plateau or a lone (overfit) spike.

These feed a ``robustness_score`` that adjusts the leaderboard ranking, so
a strategy that only looks good in-sample is penalised.
"""

from app.robustness.config import SWEEP, WF_FOLDS, sweep_for
from app.robustness.service import robustness_for, run_robustness

__all__ = ["SWEEP", "WF_FOLDS", "robustness_for", "run_robustness", "sweep_for"]

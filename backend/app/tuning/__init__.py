"""Preset tuning: robust grid search over a small parameter grid per
strategy.

The point is NOT to maximise in-sample return. Each grid point is scored on
``min(in-sample Sharpe, out-of-sample Sharpe)`` — a combo that only shines
in-sample is rejected. The winner is compared against the current
``balanced`` preset and only recommended if it is a *robust* improvement
(better on the worse of the two halves, enough trades, not ruined). If a
recommendation is adopted (``app.tuning.adopted.TUNED_PRESETS``) the
canonical leaderboard run layers those overrides on top of the preset.
"""

from app.tuning.adopted import TUNED_PRESETS, set_runtime_adoption, tuned_overrides
from app.tuning.config import TUNING_GRID, grid_for
from app.tuning.service import run_tuning, tuning_for

__all__ = [
    "TUNED_PRESETS",
    "TUNING_GRID",
    "grid_for",
    "run_tuning",
    "set_runtime_adoption",
    "tuned_overrides",
    "tuning_for",
]

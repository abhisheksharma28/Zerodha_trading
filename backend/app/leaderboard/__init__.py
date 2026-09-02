"""Strategy Leaderboard.

Ranks the library's strategy templates on two independent evidence streams:

* **Standardised backtest** — one fixed canonical config per strategy (same
  universe, window, capital, native timeframe, ``balanced`` preset), run
  through the exact production BacktestEngine + Indian cost model and cached.
  This is the only way to compare strategies apples-to-apples.
* **Live paper trading** — realised performance of the auto-created
  paper-mode deployment for each strategy, reconstructed from its fills.
  Thin or empty until a track record accumulates; shown as "collecting".

Nothing here trades real money. Backtest numbers still carry the standard
caveats (survivorship bias, out-of-sample not yet done).
"""

from app.leaderboard.config import CANONICAL, CanonicalConfig, canonical_for
from app.leaderboard.service import (
    ensure_paper_deployments,
    leaderboard,
    refresh_all,
    run_canonical,
)

__all__ = [
    "CANONICAL",
    "CanonicalConfig",
    "canonical_for",
    "ensure_paper_deployments",
    "leaderboard",
    "refresh_all",
    "run_canonical",
]

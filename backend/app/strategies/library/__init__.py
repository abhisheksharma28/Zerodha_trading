"""Strategy Library: research-backed strategy templates.

Each template is a real ``app.strategies.base.BaseStrategy`` subclass, so it
runs unchanged through the backtest engine, the simulation/paper executors
and the live router — the engine never knows a template from a hand-written
strategy. Seeding (app.seed) creates a Strategy + StrategyVersion per
template whose ``source_code`` is a one-line import shim, so strategy
versioning, the change log and the audit log all apply normally.

These are established quantitative strategy families with academic and
institutional precedent. They are NOT guaranteed, risk-free, or proven to
be profitable in the future. Every template must be validated with
out-of-sample and walk-forward testing and realistic transaction costs
before it is considered for live deployment.
"""

from app.strategies.library.base import TemplateStrategy
from app.strategies.library.mean_reversion import MeanReversionStrategy
from app.strategies.library.momentum import CrossSectionalMomentumStrategy
from app.strategies.library.opening_range_breakout import OpeningRangeBreakoutStrategy
from app.strategies.library.pairs_trading import PairsTradingStrategy
from app.strategies.library.trend_following import TrendFollowingStrategy

TEMPLATES: list[type[TemplateStrategy]] = [
    CrossSectionalMomentumStrategy,
    TrendFollowingStrategy,
    MeanReversionStrategy,
    OpeningRangeBreakoutStrategy,
    PairsTradingStrategy,
]

_BY_SLUG = {t.SLUG: t for t in TEMPLATES}


def get_template(slug: str) -> type[TemplateStrategy]:
    try:
        return _BY_SLUG[slug]
    except KeyError:
        raise KeyError(f"Unknown strategy template '{slug}'") from None


__all__ = [
    "TEMPLATES",
    "TemplateStrategy",
    "get_template",
    "CrossSectionalMomentumStrategy",
    "TrendFollowingStrategy",
    "MeanReversionStrategy",
    "OpeningRangeBreakoutStrategy",
    "PairsTradingStrategy",
]

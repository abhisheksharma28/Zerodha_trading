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
from app.strategies.library.bollinger_reversion import BollingerReversionStrategy
from app.strategies.library.chinese_transformer import ChineseTransformerStrategy
from app.strategies.library.donchian_breakout import DonchianBreakoutStrategy
from app.strategies.library.dual_momentum import DualMomentumStrategy
from app.strategies.library.fiftytwo_week_high import FiftyTwoWeekHighStrategy
from app.strategies.library.force_index import ForceIndexStrategy
from app.strategies.library.golden_cross import GoldenCrossStrategy
from app.strategies.library.index_futures_arbitrage import IndexFuturesArbitrageStrategy
from app.strategies.library.latency_arbitrage import LatencyArbitrageStrategy
from app.strategies.library.low_volatility_anomaly import LowVolatilityAnomalyStrategy
from app.strategies.library.macd_grid import MacdGridStrategy
from app.strategies.library.mean_reversion import MeanReversionStrategy
from app.strategies.library.momentum import CrossSectionalMomentumStrategy
from app.strategies.library.multi_factor import MultiFactorStrategy
from app.strategies.library.opening_breakout_us import OpeningBreakoutUSStrategy
from app.strategies.library.opening_range_breakout import OpeningRangeBreakoutStrategy
from app.strategies.library.pairs_trading import PairsTradingStrategy
from app.strategies.library.regime_adaptive import RegimeAdaptiveStrategy
from app.strategies.library.rsi2_reversion import Rsi2ReversionStrategy
from app.strategies.library.sector_momentum_rotation import SectorMomentumRotationStrategy
from app.strategies.library.supertrend import SupertrendStrategy
from app.strategies.library.trend_following import TrendFollowingStrategy
from app.strategies.library.triple_screen import TripleScreenStrategy
from app.strategies.library.volatility_regime import VolatilityRegimeStrategy
from app.strategies.library.weapon_candle import WeaponCandleStrategy
from app.strategies.library.zscore_regime import ZScoreRegimeStrategy

TEMPLATES: list[type[TemplateStrategy]] = [
    ChineseTransformerStrategy,
    CrossSectionalMomentumStrategy,
    TrendFollowingStrategy,
    DonchianBreakoutStrategy,
    MeanReversionStrategy,
    MultiFactorStrategy,
    WeaponCandleStrategy,
    MacdGridStrategy,
    ZScoreRegimeStrategy,
    TripleScreenStrategy,
    ForceIndexStrategy,
    SupertrendStrategy,
    GoldenCrossStrategy,
    Rsi2ReversionStrategy,
    BollingerReversionStrategy,
    FiftyTwoWeekHighStrategy,
    DualMomentumStrategy,
    LowVolatilityAnomalyStrategy,
    SectorMomentumRotationStrategy,
    VolatilityRegimeStrategy,
    RegimeAdaptiveStrategy,
    OpeningRangeBreakoutStrategy,
    OpeningBreakoutUSStrategy,
    PairsTradingStrategy,
    LatencyArbitrageStrategy,
    IndexFuturesArbitrageStrategy,
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
    "ChineseTransformerStrategy",
    "CrossSectionalMomentumStrategy",
    "TrendFollowingStrategy",
    "DonchianBreakoutStrategy",
    "MeanReversionStrategy",
    "MultiFactorStrategy",
    "WeaponCandleStrategy",
    "MacdGridStrategy",
    "ZScoreRegimeStrategy",
    "TripleScreenStrategy",
    "ForceIndexStrategy",
    "SupertrendStrategy",
    "GoldenCrossStrategy",
    "Rsi2ReversionStrategy",
    "BollingerReversionStrategy",
    "FiftyTwoWeekHighStrategy",
    "DualMomentumStrategy",
    "LowVolatilityAnomalyStrategy",
    "SectorMomentumRotationStrategy",
    "VolatilityRegimeStrategy",
    "RegimeAdaptiveStrategy",
    "OpeningRangeBreakoutStrategy",
    "OpeningBreakoutUSStrategy",
    "PairsTradingStrategy",
    "LatencyArbitrageStrategy",
    "IndexFuturesArbitrageStrategy",
]

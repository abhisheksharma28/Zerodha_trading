"""Chinese Transformer — cross-sectional AI stock-selection for NSE.

A cross-sectional *alpha* system: at every rebalance it ranks the whole
tradable universe by expected future risk-adjusted return and holds the
highest-conviction names. It answers "which stocks outperform the others?",
not "will stock X go up tomorrow?".

Inspired by Zhang et al., "From Attention to Profit: quantitative trading
strategy based on transformer" (arXiv:2404.00424), but deliberately not a
replica:

* multi-factor numerical input (price/momentum, volatility, volume/
  liquidity, technical structure, cross-sectional ranks, proxied market /
  sector context) rather than just past returns + turnover;
* cross-sectional rank / bucket / risk-adjusted targets, never raw price;
* chronological + walk-forward validation with a purge/embargo gap;
* an explicit data-leakage test-suite and a severity-tagged data-quality
  gate in front of every feature.

Honest limitations on this platform (see module docstrings for detail):

* the universe is today's index membership — historical runs carry
  survivorship bias, disclosed not eliminated;
* fundamentals available here are current snapshots, not point-in-time, so
  fundamental factors are live/paper only and are excluded from historical
  training;
* no India VIX / breadth / delivery-% history — market context is proxied
  from the universe's own daily bars;
* ~3-4 years of daily history from Kite, so the shipped ranker is a
  transparent linear/gradient-boosted baseline. A Transformer is only
  worth adding once the baseline shows out-of-sample Rank-IC.
"""

from __future__ import annotations

from app.chinese_transformer.data_quality import (
    DataQualityEngine,
    DataQualityIssue,
    Severity,
)
from app.chinese_transformer.features import FeaturePipeline, FeatureSpec
from app.chinese_transformer.universe import UniverseManager

__all__ = [
    "DataQualityEngine",
    "DataQualityIssue",
    "FeaturePipeline",
    "FeatureSpec",
    "Severity",
    "UniverseManager",
]

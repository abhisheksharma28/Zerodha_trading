"""Order-flow / market-microstructure analytics.

A *modular* extension on top of the existing market-data pipeline. It never
touches candlestick charting, strategies, backtesting or live execution.

Hard honesty rule (see ``capabilities.py``): Zerodha Kite streams ~1
snapshot/second with cumulative volume and a 5-level depth ladder, and its
historical API only returns >=1-minute OHLC candles. That is **not**
trade-by-trade data with an aggressor side, so a *true* Bid x Ask footprint
/ true delta / true CVD cannot be computed and is not faked here.

What this package does provide, each with an explicit data-quality tier:

* ``capabilities`` - detect and describe exactly what the feed supports.
* ``volume_profile`` - volume-at-price, POC, value area, HVN/LVN from
  1-minute candles (tier: LIMITED - documented approximation).
* ``vwap`` - session / anchored VWAP with standard-deviation bands from
  candles (tier: OK - exact).
* ``estimated_delta`` - a coarse, live-only, clearly-labelled delta/CVD
  estimate from per-snapshot volume diffs signed by the quote/tick rule
  (tier: ESTIMATED - not backfillable).
"""

from __future__ import annotations

from app.orderflow.capabilities import (
    MarketDataCapabilities,
    assess_historical,
    assess_live,
)
from app.orderflow.estimated_delta import ORDERFLOW_DELTA, EstimatedDeltaEngine
from app.orderflow.types import (
    Candle,
    DataTier,
    PriceLevel,
    VolumeProfile,
    VwapPoint,
    VwapSeries,
)
from app.orderflow.volume_profile import build_volume_profile
from app.orderflow.vwap import session_anchor_ts, vwap_series

__all__ = [
    "ORDERFLOW_DELTA",
    "Candle",
    "DataTier",
    "EstimatedDeltaEngine",
    "MarketDataCapabilities",
    "PriceLevel",
    "VolumeProfile",
    "VwapPoint",
    "VwapSeries",
    "assess_historical",
    "assess_live",
    "build_volume_profile",
    "session_anchor_ts",
    "vwap_series",
]

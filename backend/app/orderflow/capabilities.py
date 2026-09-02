"""Market-data capability detection.

The single source of truth for "what can this feed actually support?".
Every order-flow response embeds one of these so the UI can render the
``TRUE / ESTIMATED / LIMITED / UNSUPPORTED`` badge and, on click, the exact
reasons.

Currently there is one provider (Zerodha Kite). The shape is deliberately
provider-agnostic so a future tick-by-tick feed (GFDL / TrueData / exchange
TBT) is a new ``assess_*`` factory, not a rewrite of the analytics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.orderflow.types import DataTier


@dataclass
class MarketDataCapabilities:
    provider: str
    scope: str  # "live" | "historical"
    tier: DataTier

    has_ohlc: bool
    has_tick_data: bool  # true trade-by-trade prints
    has_trade_volume: bool
    has_bid_ask_quotes: bool
    has_l2_depth: bool  # full book, not a fixed top-N
    has_trade_side: bool  # exchange-provided aggressor flag
    has_sequence_numbers: bool
    timestamp_resolution: str
    historical_tick_data_available: bool

    depth_levels: int
    snapshot_hz: float | None  # approx updates/sec for a liquid instrument

    reasons: list[str] = field(default_factory=list)
    supported: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "scope": self.scope,
            "tier": self.tier.value,
            "flags": {
                "hasOHLC": self.has_ohlc,
                "hasTickData": self.has_tick_data,
                "hasTradeVolume": self.has_trade_volume,
                "hasBidAskQuotes": self.has_bid_ask_quotes,
                "hasL2Depth": self.has_l2_depth,
                "hasTradeSide": self.has_trade_side,
                "hasSequenceNumbers": self.has_sequence_numbers,
                "timestampResolution": self.timestamp_resolution,
                "historicalTickDataAvailable": self.historical_tick_data_available,
                "depthLevels": self.depth_levels,
                "snapshotHz": self.snapshot_hz,
            },
            "reasons": self.reasons,
            "supported": self.supported,
            "unsupported": self.unsupported,
        }


# Features the spec asks for, split by whether Kite data can back them honestly.
_KITE_SUPPORTED_LIVE = [
    "Volume profile / POC / value area (from 1-min bars)",
    "Session & anchored VWAP with std-dev bands",
    "Session statistics & opening-range volume/VWAP/POC",
    "DOM - 5-level depth ladder",
    "Estimated bar delta & cumulative delta (quote/tick rule, coarse)",
    "Depth-imbalance & liquidity add/reduce at the 5 visible levels (forward-only)",
]
_KITE_SUPPORTED_HIST = [
    "Volume profile / POC / value area (from 1-min bars)",
    "Session & anchored VWAP with std-dev bands",
    "Session statistics & opening-range volume/VWAP/POC",
]
_KITE_UNSUPPORTED = [
    "Bid x Ask footprint / Numbers Bars (needs trade-by-trade + side)",
    "True delta / true cumulative delta",
    "Diagonal & stacked imbalances at tick resolution",
    "Absorption & exhaustion scoring",
    "Large-trade / trade-cluster detection",
    "Full order-book liquidity heatmap (Bookmap-style)",
    "Historical tick reconstruction & tick-level market replay",
    "Order-flow backtesting on historical footprint",
]


def assess_live(provider: str = "zerodha_kite") -> MarketDataCapabilities:
    """Live Kite WebSocket in ``full`` mode."""
    return MarketDataCapabilities(
        provider=provider,
        scope="live",
        tier=DataTier.ESTIMATED,
        has_ohlc=True,
        has_tick_data=False,
        has_trade_volume=True,
        has_bid_ask_quotes=True,
        has_l2_depth=False,
        has_trade_side=False,
        has_sequence_numbers=False,
        timestamp_resolution="second",
        historical_tick_data_available=False,
        depth_levels=5,
        snapshot_hz=1.0,
        reasons=[
            "Kite streams throttled snapshots (~1/sec), not every trade print.",
            "No exchange aggressor-side flag - trade side must be inferred.",
            "Depth is the top 5 levels only; the full book is not published.",
            "Timestamps are 1-second; there are no per-trade sequence numbers.",
            "Delta/CVD here are the per-snapshot cumulative-volume change signed "
            "by the quote rule (last price vs best bid/ask), tick-rule fallback. "
            "Coarse and NOT reconstructable after the fact.",
        ],
        supported=list(_KITE_SUPPORTED_LIVE),
        unsupported=list(_KITE_UNSUPPORTED),
    )


def assess_historical(provider: str = "zerodha_kite") -> MarketDataCapabilities:
    """Kite historical REST API (>=1-minute OHLC candles)."""
    return MarketDataCapabilities(
        provider=provider,
        scope="historical",
        tier=DataTier.LIMITED,
        has_ohlc=True,
        has_tick_data=False,
        has_trade_volume=True,
        has_bid_ask_quotes=False,
        has_l2_depth=False,
        has_trade_side=False,
        has_sequence_numbers=False,
        timestamp_resolution="minute",
        historical_tick_data_available=False,
        depth_levels=0,
        snapshot_hz=None,
        reasons=[
            "Historical API returns 1-minute (or coarser) OHLCV only.",
            "No historical ticks, no historical depth snapshots.",
            "Volume profile is built by distributing each 1-min bar's volume "
            "across the prices it spanned - an approximation, not tick TPO.",
            "No side information, so profile levels have volume but no delta.",
        ],
        supported=list(_KITE_SUPPORTED_HIST),
        unsupported=list(_KITE_UNSUPPORTED),
    )

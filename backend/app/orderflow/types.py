"""Shared value types for the order-flow package.

Deliberately plain dataclasses (not pydantic) so the analytics engines stay
framework-free and trivially unit-testable; the API layer converts them to
response dicts via ``as_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DataTier(str, Enum):
    """How trustworthy an order-flow figure is, given the source feed."""

    TRUE = "TRUE_ORDER_FLOW"
    """Tick-level trades plus a reliable aggressor side."""

    ESTIMATED = "ESTIMATED_ORDER_FLOW"
    """Trade side inferred by quote/tick rule from coarse snapshots."""

    LIMITED = "LIMITED_DATA"
    """Useful volume/price info, but insufficient for real order flow."""

    UNSUPPORTED = "UNSUPPORTED"
    """OHLC only / not enough microstructure to compute this at all."""


@dataclass(frozen=True)
class Candle:
    """One OHLCV bar. ``ts`` is epoch seconds already shifted to IST
    wall-clock (matches ``market_data_service._epoch``), so profiles and
    VWAP line up with the frontend chart without re-shifting."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PriceLevel:
    """Traded volume at one price bin.

    ``buy_volume`` / ``sell_volume`` are only populated in the ESTIMATED
    live path (quote-rule classification); for the candle-derived volume
    profile they stay ``None`` because OHLC data carries no side.
    """

    price: float
    volume: float
    buy_volume: float | None = None
    sell_volume: float | None = None

    @property
    def delta(self) -> float | None:
        if self.buy_volume is None or self.sell_volume is None:
            return None
        return self.buy_volume - self.sell_volume

    def as_dict(self) -> dict[str, float | None]:
        return {
            "price": round(self.price, 4),
            "volume": round(self.volume, 4),
            "buy_volume": None if self.buy_volume is None else round(self.buy_volume, 4),
            "sell_volume": None if self.sell_volume is None else round(self.sell_volume, 4),
            "delta": None if self.delta is None else round(self.delta, 4),
        }


@dataclass
class VolumeProfile:
    bin_size: float
    levels: list[PriceLevel]
    poc_price: float | None
    vah_price: float | None
    val_price: float | None
    value_area_pct: float
    hvn_prices: list[float]
    lvn_prices: list[float]
    total_volume: float
    bars_used: int
    source_interval: str
    tier: DataTier
    method: str
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "bin_size": self.bin_size,
            "levels": [level.as_dict() for level in self.levels],
            "poc_price": self.poc_price,
            "vah_price": self.vah_price,
            "val_price": self.val_price,
            "value_area_pct": self.value_area_pct,
            "hvn_prices": self.hvn_prices,
            "lvn_prices": self.lvn_prices,
            "total_volume": round(self.total_volume, 4),
            "bars_used": self.bars_used,
            "source_interval": self.source_interval,
            "tier": self.tier.value,
            "method": self.method,
            "caveats": self.caveats,
        }


@dataclass
class VwapPoint:
    ts: int
    vwap: float
    bands: dict[str, float]  # e.g. {"upper1": .., "lower1": .., "upper2": ..}

    def as_dict(self) -> dict:
        return {"ts": self.ts, "vwap": round(self.vwap, 4),
                **{k: round(v, 4) for k, v in self.bands.items()}}


@dataclass
class VwapSeries:
    anchor_ts: int
    points: list[VwapPoint]
    band_multiples: list[float]
    tier: DataTier
    method: str

    def as_dict(self) -> dict:
        return {
            "anchor_ts": self.anchor_ts,
            "band_multiples": self.band_multiples,
            "tier": self.tier.value,
            "method": self.method,
            "points": [p.as_dict() for p in self.points],
        }

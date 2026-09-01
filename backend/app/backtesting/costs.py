"""Configurable Indian trading-cost model for backtests.

Kept completely separate from strategy logic: the same fills can be re-priced
under different cost assumptions without touching the strategy or the
engine. Charges follow the public NSE / Zerodha schedule and are
*approximate* — verify against your own broker's contract notes before
drawing conclusions. Every rate is overridable via the ``costs`` block of a
backtest run request.

Segments: ``equity_delivery`` (CNC), ``equity_intraday`` (MIS equity),
``futures`` (NRML / NFO futures), ``options`` (NFO options).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

_SEGMENTS = ("equity_delivery", "equity_intraday", "futures", "options")


@dataclass
class CostConfig:
    # Brokerage
    brokerage_flat: float = 20.0          # per executed order, intraday / F&O
    brokerage_pct: float = 0.0003         # 0.03% of turnover, capped at brokerage_flat
    brokerage_delivery_flat: float = 0.0  # Zerodha: delivery is brokerage-free

    # STT / CTT (fraction of turnover on the indicated side)
    stt_delivery_buy: float = 0.001
    stt_delivery_sell: float = 0.001
    stt_intraday_sell: float = 0.00025
    stt_futures_sell: float = 0.0002
    stt_options_sell: float = 0.001       # on premium

    # Exchange transaction charges (fraction of turnover, both sides)
    exch_txn_equity: float = 0.0000297
    exch_txn_futures: float = 0.0000173
    exch_txn_options: float = 0.0003503

    # SEBI turnover fee (both sides, all segments): ~Rs 10 per crore
    sebi_fee: float = 0.000001

    # Stamp duty (buy side only, fraction of turnover)
    stamp_delivery_buy: float = 0.00015
    stamp_intraday_buy: float = 0.00003
    stamp_futures_buy: float = 0.00002
    stamp_options_buy: float = 0.00003

    # GST on (brokerage + exchange txn + SEBI fee)
    gst_rate: float = 0.18

    # Execution slippage applied to every fill, in basis points of price.
    slippage_bps: float = 2.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CostConfig:
        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown cost config key(s): {sorted(unknown)}")
        return cls(**{k: float(v) for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostBreakdown:
    brokerage: float = 0.0
    stt: float = 0.0
    exchange_txn: float = 0.0
    gst: float = 0.0
    sebi: float = 0.0
    stamp_duty: float = 0.0
    slippage: float = 0.0

    @property
    def statutory_total(self) -> float:
        return self.brokerage + self.stt + self.exchange_txn + self.gst + self.sebi + self.stamp_duty

    @property
    def total(self) -> float:
        return self.statutory_total + self.slippage

    def add(self, other: CostBreakdown) -> CostBreakdown:
        return CostBreakdown(
            brokerage=self.brokerage + other.brokerage,
            stt=self.stt + other.stt,
            exchange_txn=self.exchange_txn + other.exchange_txn,
            gst=self.gst + other.gst,
            sebi=self.sebi + other.sebi,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            slippage=self.slippage + other.slippage,
        )

    def to_dict(self) -> dict[str, float]:
        d = {f.name: round(getattr(self, f.name), 4) for f in fields(self)}
        d["statutory_total"] = round(self.statutory_total, 4)
        d["total"] = round(self.total, 4)
        return d


class CostModel:
    def __init__(self, config: CostConfig | None = None) -> None:
        self.config = config or CostConfig()

    @staticmethod
    def segment_for(product: str, exchange: str) -> str:
        ex = (exchange or "").upper()
        prod = (product or "").upper()
        if ex in ("NFO", "BFO", "MCX"):
            return "options" if prod == "OPT" else "futures"
        return "equity_intraday" if prod == "MIS" else "equity_delivery"

    def fill_price_with_slippage(self, side: str, price: float, *, segment: str = "") -> float:
        bps = self.config.slippage_bps / 1e4
        return price * (1.0 + bps) if side.upper() == "BUY" else price * (1.0 - bps)

    def charge(
        self, side: str, price: float, quantity: int, segment: str, *, reference_price: float
    ) -> CostBreakdown:
        """``price`` is the (post-slippage) fill price; ``reference_price`` is
        the pre-slippage price, used to size the slippage cost."""
        cfg = self.config
        side = side.upper()
        turnover = price * quantity
        b = CostBreakdown()

        # brokerage
        if segment == "equity_delivery":
            b.brokerage = cfg.brokerage_delivery_flat
        else:
            b.brokerage = min(cfg.brokerage_flat, cfg.brokerage_pct * turnover)

        # STT
        if segment == "equity_delivery":
            b.stt = (cfg.stt_delivery_buy if side == "BUY" else cfg.stt_delivery_sell) * turnover
        elif segment == "equity_intraday":
            b.stt = cfg.stt_intraday_sell * turnover if side == "SELL" else 0.0
        elif segment == "futures":
            b.stt = cfg.stt_futures_sell * turnover if side == "SELL" else 0.0
        else:  # options
            b.stt = cfg.stt_options_sell * turnover if side == "SELL" else 0.0

        # exchange transaction charges
        if segment == "futures":
            b.exchange_txn = cfg.exch_txn_futures * turnover
        elif segment == "options":
            b.exchange_txn = cfg.exch_txn_options * turnover
        else:
            b.exchange_txn = cfg.exch_txn_equity * turnover

        # SEBI
        b.sebi = cfg.sebi_fee * turnover

        # stamp duty (buy only)
        if side == "BUY":
            b.stamp_duty = {
                "equity_delivery": cfg.stamp_delivery_buy,
                "equity_intraday": cfg.stamp_intraday_buy,
                "futures": cfg.stamp_futures_buy,
                "options": cfg.stamp_options_buy,
            }[segment] * turnover

        # GST on brokerage + exchange txn + SEBI
        b.gst = cfg.gst_rate * (b.brokerage + b.exchange_txn + b.sebi)

        # slippage cost vs the reference (pre-slippage) price
        b.slippage = abs(price - reference_price) * quantity

        return b

"""Shared types for scheduled options-basket strategies.

The strategy is pure, deterministic logic: given ``as_of`` and a
``MarketData`` view it returns an ENTRY decision; given a live state and
current prices it returns an EXIT decision. It never talks to a broker, the
database, or the clock directly — the execution layer (backtest / paper /
live worker) supplies the MarketData implementation and turns the returned
signals into simulated or real orders. This is what keeps backtest and live
behaviour identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol


@dataclass
class OptionLeg:
    label: str            # "A" | "B" | "C"
    action: str           # "BUY" | "SELL"
    option_type: str      # "CE"
    strike: float
    expiry: date
    lots: int             # quantity multiplier from config
    lot_size: int
    tradingsymbol: str
    instrument_token: str
    theoretical_strike: float = 0.0
    strike_difference: float = 0.0
    entry_price: float = 0.0   # per unit, filled at execution time

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def signed_dir(self) -> int:
        return 1 if self.action == "BUY" else -1

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["expiry"] = self.expiry.isoformat()
        d["quantity"] = self.quantity
        return d


@dataclass
class BasketSpec:
    underlying: str
    expiry: date
    spot_at_entry: float
    lot_size: int
    legs: list[OptionLeg]
    net_credit: float          # INR, whole basket; positive = credit received
    credit_pct: float          # net_credit / deployed_capital * 100
    deployed_capital: float
    deployed_capital_source: str  # "broker" | "fallback"
    target_amount: float       # INR, positive
    stop_loss_amount: float     # INR, positive
    short_strike: float        # strike of the short leg (B)

    def to_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "spot_at_entry": self.spot_at_entry,
            "lot_size": self.lot_size,
            "legs": [leg.to_dict() for leg in self.legs],
            "net_credit": round(self.net_credit, 2),
            "credit_pct": round(self.credit_pct, 4),
            "deployed_capital": round(self.deployed_capital, 2),
            "deployed_capital_source": self.deployed_capital_source,
            "target_amount": round(self.target_amount, 2),
            "stop_loss_amount": round(self.stop_loss_amount, 2),
            "short_strike": self.short_strike,
        }


@dataclass
class EntryDecision:
    eligible: bool
    reason: str
    as_of: datetime
    spot: float | None = None
    expiry: date | None = None
    dte: int | None = None
    basket: BasketSpec | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str          # "" | TARGET | STOP_LOSS | SHORT_STRIKE_EXIT | TIME_EXIT | EXPIRY_EXIT
    pnl: float
    pnl_pct: float
    detail: str = ""


@dataclass
class LegQuote:
    bid: float
    ask: float
    last: float
    volume: float = 0.0
    oi: float = 0.0

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread_pct(self) -> float:
        m = self.mid
        return abs(self.ask - self.bid) / m * 100.0 if m > 0 else float("inf")


class MarketData(Protocol):
    """Everything a scheduled options strategy is allowed to read. Implemented
    once for live (Kite), once for backtest (historical source)."""

    def spot(self, underlying: str, as_of: datetime) -> float | None: ...

    def call_strikes(self, underlying: str, expiry: date, as_of: datetime) -> list[float]: ...

    def option_quote(
        self, underlying: str, expiry: date, strike: float, option_type: str, as_of: datetime
    ) -> LegQuote | None: ...

    def basket_margin(self, legs: list[OptionLeg], as_of: datetime) -> float | None:
        """Broker margin (deployed capital) for the whole basket, or None if
        it cannot be determined and the caller should fall back."""
        ...

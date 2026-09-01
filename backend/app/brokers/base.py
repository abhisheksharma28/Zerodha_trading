"""Abstract broker interface.

Every broker integration (currently only Zerodha Kite Connect) implements
this Protocol. Nothing outside app/brokers/ should import
app.brokers.zerodha directly except the factory in this file — the execution
layer only ever depends on BrokerClient, so swapping/adding a broker never
touches app/execution, app/strategies, or the API layer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class PlacedOrderResult:
    broker_order_id: str
    raw_response: dict[str, Any]


@dataclass
class OrderRequest:
    tradingsymbol: str
    exchange: str
    transaction_type: str  # BUY | SELL
    order_type: str  # MARKET | LIMIT | SL | SL-M
    quantity: int
    product: str  # CNC | MIS | NRML | MTF
    price: float | None = None
    trigger_price: float | None = None
    validity: str = "DAY"
    variety: str = "regular"
    market_protection: float | None = None  # required for MARKET/SL-M — see order_builder


class BrokerClient(Protocol):
    """Protocol every broker adapter must satisfy. Kept intentionally small —
    anything broker-specific belongs behind this interface, never leaking
    Kite-shaped types into app.execution / app.strategies."""

    def get_login_url(self) -> str: ...

    def generate_session(self, request_token: str) -> "BrokerSessionData": ...

    def place_order(self, order: OrderRequest) -> PlacedOrderResult: ...

    def cancel_order(self, broker_order_id: str, *, variety: str = "regular") -> None: ...

    def get_positions(self) -> dict[str, Any]: ...

    def get_holdings(self) -> list[dict[str, Any]]: ...

    def get_margins(self) -> dict[str, Any]: ...

    def get_historical_candles(
        self, instrument_token: str, interval: str, from_dt: datetime, to_dt: datetime
    ) -> list[list[Any]]: ...


@dataclass
class BrokerSessionData:
    access_token: str
    public_token: str | None
    kite_user_id: str | None
    expires_at: datetime


class BaseBroker(ABC):
    """Optional ABC with shared plumbing (rate limiting hooks, logging)
    concrete brokers can subclass instead of implementing BrokerClient from
    scratch."""

    name: str

    @abstractmethod
    def get_login_url(self) -> str: ...

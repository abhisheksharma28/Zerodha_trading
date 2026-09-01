"""Base class every user-authored strategy implements.

A StrategyVersion.source_code file must define exactly one subclass of
BaseStrategy (named by StrategyVersion.entry_point). The same subclass runs
unmodified in backtesting, simulation, paper, and live — it never touches a
broker or the database directly, only the `context` handed to it. This is
what guarantees behavioural parity across modes: the only thing that
changes between modes is what OrderRouter does with the OrderRequest the
strategy emits, never the strategy's own decision logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.brokers.base import OrderRequest


@dataclass
class Bar:
    timestamp: Any
    open: float
    high: float
    low: float
    close: float
    volume: float
    instrument: str


@dataclass
class StrategyContext:
    """Everything a strategy is allowed to see. Notably: no direct DB
    session, no broker client — only read access to data and a place to
    queue order intents, which OrderRouter (chosen by the deployment's mode,
    not by the strategy) turns into real/paper/simulated fills."""

    parameters: dict[str, Any]
    positions: dict[str, int] = field(default_factory=dict)  # instrument -> net qty
    _pending_orders: list[OrderRequest] = field(default_factory=list)
    signals: dict[str, int] = field(default_factory=dict)  # optional diagnostics counters

    def submit_order(self, order: OrderRequest) -> None:
        self._pending_orders.append(order)

    def drain_pending_orders(self) -> list[OrderRequest]:
        pending, self._pending_orders = self._pending_orders, []
        return pending

    def note_signal(self, label: str, n: int = 1) -> None:
        """Optional: record that the strategy produced a signal of some kind
        this bar (e.g. "long_entry", "exit", "filtered_out"). Purely for
        backtest diagnostics — it never affects execution. Strategies that
        don't call this simply contribute nothing to the signal report."""
        self.signals[label] = self.signals.get(label, 0) + int(n)


class BaseStrategy(ABC):
    """Subclass this. `on_bar` is called once per new bar/tick for each
    subscribed instrument, in every mode."""

    def __init__(self, context: StrategyContext) -> None:
        self.context = context

    def on_start(self) -> None:
        """Called once when the strategy is deployed/backtest begins."""

    @abstractmethod
    def on_bar(self, bar: Bar) -> None:
        """Called for every new bar. Call self.context.submit_order(...) to
        express trade intent — do not call any broker/database API here."""

    def on_stop(self) -> None:
        """Called once on deliberate stop (not on pause)."""

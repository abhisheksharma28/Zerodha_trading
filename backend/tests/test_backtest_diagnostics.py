"""Backtest run diagnostics + the zero-trade explainer."""

from __future__ import annotations

from app.backtesting.diagnostics import RunDiagnostics, explain_no_trades
from app.backtesting.engine import BacktestEngine
from app.brokers.base import OrderRequest
from app.strategies.base import Bar, BaseStrategy


class _Idle(BaseStrategy):
    def on_bar(self, bar: Bar) -> None:
        self.context.note_signal("looked_at_bar")


class _BuysOnceThenNothing(BaseStrategy):
    def on_bar(self, bar: Bar) -> None:
        if not self.context.positions.get(bar.instrument):
            self.context.note_signal("long_entry")
            self.context.submit_order(OrderRequest(
                tradingsymbol=bar.instrument, exchange="NSE", transaction_type="BUY",
                order_type="MARKET", quantity=5, product="CNC",
            ))


class _EmitsZeroQtyOrders(BaseStrategy):
    def on_bar(self, bar: Bar) -> None:
        self.context.note_signal("long_entry")
        self.context.submit_order(OrderRequest(
            tradingsymbol=bar.instrument, exchange="NSE", transaction_type="BUY",
            order_type="MARKET", quantity=0, product="CNC",
        ))


def _bars(prices, sym="TEST"):
    return [Bar(timestamp=f"2026-01-{i+1:02d}T00:00:00+05:30", open=p, high=p, low=p,
                close=p, volume=1000, instrument=sym) for i, p in enumerate(prices)]


def test_diagnostics_populated_on_a_trading_run():
    res = BacktestEngine(_BuysOnceThenNothing, {}, 100_000).run({"TEST": _bars([100, 101, 102])})
    d = res.diagnostics
    assert d.total_bars == 3
    assert d.bars_by_instrument == {"TEST": 3}
    assert d.orders_submitted == 1 and d.fills == 1 and d.rejected_orders == 0
    assert d.signals.get("long_entry") == 1
    assert d.first_bar_ts and d.last_bar_ts


def test_diagnostics_counts_rejected_zero_qty_orders():
    res = BacktestEngine(_EmitsZeroQtyOrders, {}, 100_000).run({"TEST": _bars([100, 101, 102])})
    d = res.diagnostics
    assert d.orders_submitted == 3
    assert d.fills == 0
    assert d.rejected_orders == 3
    assert d.rejection_reasons.get("zero/negative quantity") == 3


def test_explain_no_trades_when_no_data():
    diag = RunDiagnostics(total_bars=0)
    dq = {"ok": False, "errors": ["INFY: no candles"], "warnings": [],
          "per_symbol": [{"symbol": "INFY", "bars": 0}]}
    reasons = explain_no_trades(diag, dq, timeframe="5m")
    assert reasons and "No candle data" in reasons[0] and "INFY" in reasons[0]


def test_explain_no_trades_when_conditions_never_met():
    diag = RunDiagnostics(total_bars=500, bars_by_instrument={"INFY": 500},
                          orders_submitted=0, signals={})
    reasons = explain_no_trades(diag, {"warnings": [], "per_symbol": [{"symbol": "INFY", "bars": 500}]},
                                timeframe="1d")
    assert any("entry conditions were never satisfied" in r for r in reasons)


def test_explain_no_trades_signals_but_no_orders():
    diag = RunDiagnostics(total_bars=500, bars_by_instrument={"INFY": 500},
                          orders_submitted=0, signals={"long_entry": 12})
    reasons = explain_no_trades(diag, {"warnings": [], "per_symbol": []}, timeframe="1d")
    assert any("never sized a position" in r for r in reasons)


def test_explain_no_trades_all_orders_rejected():
    diag = RunDiagnostics(total_bars=500, bars_by_instrument={"INFY": 500},
                          orders_submitted=4, fills=0,
                          rejection_reasons={"zero/negative quantity": 4})
    reasons = explain_no_trades(diag, {"warnings": [], "per_symbol": []}, timeframe="1d")
    assert any("all were rejected before fill" in r for r in reasons)


def test_explain_no_trades_thin_history():
    diag = RunDiagnostics(total_bars=10, bars_by_instrument={"INFY": 10}, orders_submitted=0)
    reasons = explain_no_trades(diag, {"warnings": [], "per_symbol": [{"symbol": "INFY", "bars": 10}]},
                                timeframe="1d", min_bars_required=125)
    assert any("warm-up" in r for r in reasons)

from app.backtesting.engine import BacktestEngine
from app.backtesting.metrics import compute_metrics
from app.brokers.base import OrderRequest
from app.strategies.base import Bar, BaseStrategy


class _BuyAndHoldOnFirstBar(BaseStrategy):
    """Minimal strategy used purely to exercise the engine end-to-end."""

    def on_bar(self, bar: Bar) -> None:
        if not self.context.positions.get(bar.instrument):
            self.context.submit_order(
                OrderRequest(
                    tradingsymbol=bar.instrument,
                    exchange="NSE",
                    transaction_type="BUY",
                    order_type="MARKET",
                    quantity=10,
                    product="CNC",
                )
            )


def _make_bars(prices: list[float], instrument: str = "TEST") -> list[Bar]:
    return [
        Bar(timestamp=i, open=p, high=p, low=p, close=p, volume=1000, instrument=instrument)
        for i, p in enumerate(prices)
    ]


def test_engine_buys_once_and_marks_to_market():
    bars = _make_bars([100, 102, 101, 105, 110])
    engine = BacktestEngine(_BuyAndHoldOnFirstBar, parameters={}, initial_capital=10_000)

    result = engine.run({"TEST": bars})

    assert result.final_positions == {"TEST": 10}
    assert len(result.fills) == 1
    assert result.fills[0].price == 100
    # cash after buying 10 @ 100 = 10000 - 1000 = 9000, plus 10 units marked
    # at the final close of 110 => 9000 + 1100 = 10100
    assert result.equity_curve[-1][1] == 10_100


def test_engine_never_trades_without_signal():
    class _DoNothing(BaseStrategy):
        def on_bar(self, bar: Bar) -> None:
            pass

    bars = _make_bars([100, 101, 99])
    engine = BacktestEngine(_DoNothing, parameters={}, initial_capital=5_000)
    result = engine.run({"TEST": bars})

    assert result.fills == []
    assert result.final_positions == {}
    assert all(v == 5_000 for _, v in result.equity_curve)


def test_compute_metrics_flat_equity_curve_has_zero_return():
    metrics = compute_metrics([("t0", 1000.0), ("t1", 1000.0), ("t2", 1000.0)])
    assert metrics["total_return_pct"] == 0.0
    assert metrics["max_drawdown_pct"] == 0.0


def test_compute_metrics_detects_drawdown():
    metrics = compute_metrics([("t0", 1000.0), ("t1", 1200.0), ("t2", 900.0), ("t3", 1100.0)])
    # peak 1200 -> trough 900 => 25% drawdown
    assert metrics["max_drawdown_pct"] == 25.0

"""BacktestEngine solvency guards: gross-exposure cap + ruin halt.

Regression cover for the multi-instrument over-leverage blow-up (a 1%-risk
strategy printing -593% return / -441% worst day because N concurrent
positions each sized off full capital compounded into a 20x book and the
equity curve crossed zero).
"""

from __future__ import annotations

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.engine import BacktestEngine
from app.strategies.base import Bar, BaseStrategy


class _BuyEverythingEachBar(BaseStrategy):
    """Pathological: tries to buy 1000 shares of every symbol, every bar —
    unbounded leverage if the engine doesn't stop it."""

    def on_bar(self, bar: Bar) -> None:
        from app.brokers.base import OrderRequest

        self.context.submit_order(OrderRequest(
            tradingsymbol=bar.instrument, exchange="NSE", transaction_type="BUY",
            order_type="MARKET", quantity=1000, product="MIS",
        ))


def _bars(sym: str, prices: list[float]) -> list[Bar]:
    return [
        Bar(timestamp=f"2026-01-{i + 1:02d}T09:15:00+05:30", open=p, high=p, low=p,
            close=p, volume=1_000_000.0, instrument=sym)
        for i, p in enumerate(prices)
    ]


def _dataset(n_syms: int, n_bars: int, start: float, drift: float) -> dict[str, list[Bar]]:
    return {
        f"S{k}": _bars(f"S{k}", [start + drift * i for i in range(n_bars)])
        for k in range(n_syms)
    }


def test_gross_exposure_cap_bounds_the_book():
    candles = _dataset(6, 10, start=100.0, drift=0.0)
    res = BacktestEngine(
        _BuyEverythingEachBar, {}, initial_capital=1_000_000.0,
        cost_model=CostModel(CostConfig()), max_gross_exposure=2.0,
    ).run(candles)
    # 6 syms x 1000 sh x 100 = 600k per bar of demand; cap = 2x1M = 2M.
    # Peak gross exposure must never exceed the cap (small rounding slack).
    assert res.diagnostics.peak_gross_exposure_pct <= 200.0 + 1e-6
    assert res.diagnostics.exposure_capped_orders > 0
    assert not res.diagnostics.ruined


def test_uncapped_engine_is_unchanged():
    candles = _dataset(3, 5, start=100.0, drift=0.0)
    res = BacktestEngine(_BuyEverythingEachBar, {}, initial_capital=1_000_000.0).run(candles)
    assert res.diagnostics.exposure_capped_orders == 0
    # 3 syms x 1000 x 100 x 5 bars of buying, no cap -> way past 100%
    assert res.diagnostics.peak_gross_exposure_pct > 100.0


def test_ruin_halt_freezes_trading_when_equity_hits_zero():
    # long a big book, then price collapses to ~0 -> equity crosses zero
    prices_up = [100.0] * 3
    crash = [100.0, 50.0, 5.0, 0.5, 0.5, 0.5]
    candles = {"S0": _bars("S0", prices_up + crash)}
    res = BacktestEngine(
        _BuyEverythingEachBar, {}, initial_capital=100_000.0,
        cost_model=CostModel(CostConfig()), max_gross_exposure=5.0,
    ).run(candles)
    assert res.diagnostics.ruined
    assert res.diagnostics.ruin_ts is not None
    # equity curve still spans every bar, and never recovers after ruin
    assert len(res.equity_curve) == 9
    ruin_idx = next(i for i, (_, v) in enumerate(res.equity_curve) if v <= 0)
    fills_after_ruin = [f for f in res.fills
                        if str(f.bar_timestamp) > res.diagnostics.ruin_ts]
    assert not fills_after_ruin, "no new fills once the book is bankrupt"
    assert ruin_idx >= 0


def test_closing_orders_are_never_blocked_by_the_cap():
    """A reducing order must always go through even at the exposure ceiling."""
    from app.brokers.base import OrderRequest

    class _OpenThenClose(BaseStrategy):
        def on_bar(self, bar: Bar) -> None:
            n = self.context.positions.get(bar.instrument, 0)
            if n == 0:
                self.context.submit_order(OrderRequest(
                    tradingsymbol=bar.instrument, exchange="NSE", transaction_type="BUY",
                    order_type="MARKET", quantity=5000, product="MIS"))
            else:
                self.context.submit_order(OrderRequest(
                    tradingsymbol=bar.instrument, exchange="NSE", transaction_type="SELL",
                    order_type="MARKET", quantity=n, product="MIS"))

    candles = {"S0": _bars("S0", [100.0] * 6)}
    res = BacktestEngine(
        _OpenThenClose, {}, initial_capital=100_000.0,
        cost_model=CostModel(CostConfig()), max_gross_exposure=1.0,
    ).run(candles)
    # opened (capped to ~1000 sh = 100k), then fully closed back to flat
    assert res.final_positions.get("S0", 0) == 0

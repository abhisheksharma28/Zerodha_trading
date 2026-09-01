"""Cost model, trade reconstruction and expanded-metrics tests (no DB)."""

import math

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.engine import BacktestEngine, SimulatedFill
from app.backtesting.performance import build_charts, compute_performance
from app.backtesting.trades import reconstruct_trades
from app.brokers.base import OrderRequest
from app.strategies.base import Bar, BaseStrategy


def test_cost_config_rejects_unknown_keys():
    try:
        CostConfig.from_dict({"not_a_real_rate": 1.0})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_segment_mapping():
    m = CostModel()
    assert m.segment_for("CNC", "NSE") == "equity_delivery"
    assert m.segment_for("MIS", "NSE") == "equity_intraday"
    assert m.segment_for("NRML", "NFO") == "futures"
    assert m.segment_for("OPT", "NFO") == "options"


def test_delivery_buy_has_no_brokerage_but_has_stt_and_stamp():
    m = CostModel()
    cb = m.charge("BUY", 100.0, 100, "equity_delivery", reference_price=100.0)
    assert cb.brokerage == 0.0
    assert math.isclose(cb.stt, 0.001 * 100 * 100)          # 0.1% delivery buy
    assert math.isclose(cb.stamp_duty, 0.00015 * 100 * 100)  # stamp duty on buy
    assert cb.total > 0


def test_intraday_stt_only_on_sell_and_slippage_direction():
    m = CostModel(CostConfig(slippage_bps=10.0))
    buy_px = m.fill_price_with_slippage("BUY", 200.0)
    sell_px = m.fill_price_with_slippage("SELL", 200.0)
    assert buy_px > 200.0 > sell_px
    buy = m.charge("BUY", buy_px, 50, "equity_intraday", reference_price=200.0)
    sell = m.charge("SELL", sell_px, 50, "equity_intraday", reference_price=200.0)
    assert buy.stt == 0.0
    assert sell.stt > 0.0
    assert buy.slippage > 0 and sell.slippage > 0


def test_zeroed_config_produces_zero_cost():
    z = dict.fromkeys(CostConfig().to_dict(), 0.0)
    m = CostModel(CostConfig.from_dict(z))
    cb = m.charge("SELL", 500.0, 10, "futures", reference_price=500.0)
    assert cb.total == 0.0


# --- engine integration -------------------------------------------------

class _BuyThenSell(BaseStrategy):
    def on_bar(self, bar: Bar) -> None:
        held = self.context.positions.get(bar.instrument, 0)
        if held == 0 and bar.close < 105:
            self.context.submit_order(OrderRequest(
                tradingsymbol=bar.instrument, exchange="NSE", transaction_type="BUY",
                order_type="MARKET", quantity=100, product="MIS"))
        elif held > 0 and bar.close >= 110:
            self.context.submit_order(OrderRequest(
                tradingsymbol=bar.instrument, exchange="NSE", transaction_type="SELL",
                order_type="MARKET", quantity=100, product="MIS"))


def _bars(prices):
    return [Bar(timestamp=f"2026-01-{i + 1:02d}T00:00:00+05:30", open=p, high=p, low=p,
                close=p, volume=100000, instrument="X") for i, p in enumerate(prices)]


def test_engine_applies_costs_and_reduces_pnl_vs_gross():
    prices = [100, 101, 108, 112, 111]
    gross = BacktestEngine(_BuyThenSell, {}, 1_000_000).run({"X": _bars(prices)})
    net = BacktestEngine(_BuyThenSell, {}, 1_000_000,
                         cost_model=CostModel(CostConfig(slippage_bps=5.0))).run({"X": _bars(prices)})
    assert net.total_costs > 0
    assert net.equity_curve[-1][1] < gross.equity_curve[-1][1]
    assert net.cost_breakdown["total"] > 0
    assert all(f.cost >= 0 for f in net.fills)


def test_trade_reconstruction_pairs_entry_and_exit():
    fills = [
        SimulatedFill("2026-01-01T00:00:00+05:30", "X", "BUY", 100, 100.0),
        SimulatedFill("2026-01-05T00:00:00+05:30", "X", "SELL", 100, 112.0),
    ]
    trades = reconstruct_trades(fills, fill_costs=[50.0, 60.0])
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "long" and t.quantity == 100
    assert math.isclose(t.gross_pnl, 1200.0)
    assert math.isclose(t.costs, 110.0)
    assert math.isclose(t.net_pnl, 1090.0)
    assert not t.is_open


def test_trade_reconstruction_reports_open_position_marked_to_market():
    fills = [SimulatedFill("2026-01-01T00:00:00+05:30", "X", "BUY", 10, 100.0)]
    trades = reconstruct_trades(fills, fill_costs=[5.0], mark_prices={"X": 130.0})
    assert len(trades) == 1 and trades[0].is_open
    assert math.isclose(trades[0].gross_pnl, 300.0)


def test_expanded_metrics_and_charts_shapes():
    equity = [(f"2026-0{1 + i // 28}-{1 + i % 28:02d}T00:00:00+05:30", 1_000_000 + i * 400)
              for i in range(60)]
    fills = [
        SimulatedFill(equity[5][0], "X", "BUY", 100, 100.0),
        SimulatedFill(equity[15][0], "X", "SELL", 100, 108.0),
        SimulatedFill(equity[20][0], "X", "BUY", 100, 110.0),
        SimulatedFill(equity[30][0], "X", "SELL", 100, 104.0),
    ]
    trades = reconstruct_trades(fills, fill_costs=[20, 20, 20, 20])
    m = compute_performance(equity, trades, initial_capital=1_000_000, total_costs=80.0)
    for key in ("net_pnl", "gross_pnl", "total_costs", "sortino_ratio", "calmar_ratio",
                "profit_factor", "win_rate_pct", "total_trades", "avg_winner", "avg_loser",
                "largest_winner", "largest_loser", "max_consecutive_losses", "turnover_ratio",
                "capital_utilization_pct"):
        assert key in m
    assert m["total_trades"] == 2
    charts = build_charts(equity, trades, 1_000_000)
    assert set(charts) == {"drawdown_curve", "monthly_returns", "daily_pnl", "exposure_curve",
                           "trade_return_distribution"}
    assert len(charts["drawdown_curve"]) == len(equity)
    assert all(dd <= 0 for _, dd in charts["drawdown_curve"])

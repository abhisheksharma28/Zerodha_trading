"""End-to-end backtest of the `donchian-breakout` template.

Runs the real BacktestEngine + Indian CostModel over a deterministic
multi-instrument daily dataset and checks the full pipeline:
data-quality validation -> engine fills -> trade reconstruction ->
performance metrics.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.performance import compute_performance
from app.backtesting.trades import reconstruct_trades
from app.strategies.base import Bar
from app.strategies.library import DonchianBreakoutStrategy

IST = "+05:30"
UNIVERSE = ["ALPHA", "BRAVO", "CHARLIE"]


def _ts(day: date) -> str:
    return datetime(day.year, day.month, day.day, 0, 0).strftime("%Y-%m-%dT%H:%M:00") + IST


def _weekdays(n: int, start=date(2026, 1, 5)) -> list[date]:
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _series(offset: int) -> list[float]:
    """25 ranging bars, a 20-bar uptrend (triggers the 20-bar breakout),
    then a sharp reversal that trips the exit channel / ATR stop."""
    ramp_up = [100 + (i % 3 - 1) + offset for i in range(25)]
    trend = [ramp_up[-1] + 2.5 * i for i in range(1, 21)]
    reversal = [trend[-1] - 9 * i for i in range(1, 8)]
    return [float(x) for x in ramp_up + trend + reversal]


def _dataset() -> dict[str, list[Bar]]:
    days = _weekdays(52)
    out: dict[str, list[Bar]] = {}
    for k, sym in enumerate(UNIVERSE):
        closes = _series(k * 3)
        bars = []
        for i, c in enumerate(closes):
            bars.append(Bar(timestamp=_ts(days[i]), open=c, high=c + 1.5, low=c - 1.5,
                            close=c, volume=150_000.0, instrument=sym))
        out[sym] = bars
    return out


def _params(**over):
    p = dict(DonchianBreakoutStrategy.presets()["balanced"])
    p.update(entry_period=20, exit_period=10, atr_period=14, atr_stop_mult=2.0,
             trailing_atr_mult=0.0, rvol_min=0.0, adx_min=0.0, atr_expansion_min=0.0,
             allow_short=False, regime_filter_enabled=False,
             sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
             capital_allocation=2_000_000.0, max_position_size_pct=25.0, product="CNC")
    p.update(over)
    return DonchianBreakoutStrategy.resolve_params(p)


def test_donchian_backtest_flows_end_to_end(capsys):
    candles = _dataset()
    dq = validate_candles(candles)
    assert dq["ok"], dq["errors"]

    total_bars = sum(len(v) for v in candles.values())
    engine = BacktestEngine(
        DonchianBreakoutStrategy, _params(), initial_capital=2_000_000.0,
        cost_model=CostModel(CostConfig()),
    )
    result = engine.run(candles)

    assert result.fills, "expected breakout entries on the trending leg"
    assert len(result.equity_curve) == total_bars
    assert result.total_costs > 0
    # the reversal leg must flatten every position (channel or ATR exit)
    assert all(q == 0 for q in result.final_positions.values()), result.final_positions

    mark = {s: b[-1].close for s, b in candles.items() if b}
    trades = reconstruct_trades(result.fills, fill_costs=[f.cost for f in result.fills],
                                mark_prices=mark)
    perf = compute_performance(result.equity_curve, trades, initial_capital=2_000_000.0,
                               total_costs=result.total_costs)
    for key in ("return_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                "calmar_ratio", "win_rate_pct", "profit_factor", "total_trades",
                "avg_trade", "turnover_ratio"):
        assert key in perf

    with capsys.disabled():
        print(
            f"\n[donchian breakout] {len(UNIVERSE)} instruments, {total_bars} bars, "
            f"{len(result.fills)} fills, {perf['total_trades']} closed trades  "
            f"net {perf['net_pnl']:.0f}  costs {result.total_costs:.0f}"
        )


def test_donchian_zero_cost_keeps_more_pnl_than_costed():
    candles = _dataset()
    p = _params()
    costed = BacktestEngine(DonchianBreakoutStrategy, p, 2_000_000.0,
                            cost_model=CostModel(CostConfig())).run(candles)
    free = BacktestEngine(
        DonchianBreakoutStrategy, p, 2_000_000.0,
        cost_model=CostModel(CostConfig(
            brokerage_flat=0.0, brokerage_pct=0.0, stt_delivery_buy=0.0, stt_delivery_sell=0.0,
            stt_intraday_sell=0.0, exch_txn_equity=0.0, sebi_fee=0.0, stamp_delivery_buy=0.0,
            stamp_intraday_buy=0.0, gst_rate=0.0, slippage_bps=0.0,
        )),
    ).run(candles)
    assert free.total_costs == 0.0
    assert costed.total_costs > 0.0
    assert free.equity_curve[-1][1] >= costed.equity_curve[-1][1]

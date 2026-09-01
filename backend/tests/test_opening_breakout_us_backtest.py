"""End-to-end backtest of the `opening breakout US` template.

Runs the real BacktestEngine + Indian CostModel over a multi-instrument
synthetic intraday dataset and checks that data flows through every stage:
data-quality validation -> engine fills -> trade reconstruction ->
performance metrics. Deterministic (fixed synthetic data, no randomness).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.performance import compute_performance
from app.backtesting.trades import reconstruct_trades
from app.strategies.base import Bar
from app.strategies.library import OpeningBreakoutUSStrategy

IST = "+05:30"
UNIVERSE = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT"]


def _ts(day: date, minute: int) -> str:
    base = datetime(day.year, day.month, day.day, 9, 15) + timedelta(minutes=minute)
    return base.strftime("%Y-%m-%dT%H:%M:00") + IST


def _weekdays(n: int, start=date(2026, 1, 5)) -> list[date]:
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _day_bars(sym: str, day: date, *, level: float, or_open: float, or_close: float,
              or_vol: float, post_close: float, post_vol: float) -> list[Bar]:
    or_high, or_low = level + 1.0, level - 1.0
    hi2 = max(or_high, or_open, or_close, post_close) + 0.3
    lo2 = min(or_low, or_open, or_close, post_close) - 0.3
    return [
        Bar(timestamp=_ts(day, 0), open=or_open, high=max(or_high, or_open, or_close),
            low=min(or_low, or_open, or_close), close=or_close, volume=or_vol, instrument=sym),
        Bar(timestamp=_ts(day, 5), open=or_close, high=hi2, low=lo2, close=post_close,
            volume=post_vol, instrument=sym),
        Bar(timestamp=_ts(day, 10), open=post_close, high=post_close + 0.4,
            low=post_close - 0.4, close=post_close, volume=post_vol, instrument=sym),
        Bar(timestamp=_ts(day, 365), open=post_close, high=post_close + 0.4,
            low=post_close - 0.4, close=post_close, volume=40_000.0, instrument=sym),
    ]


def _dataset() -> dict[str, list[Bar]]:
    """40 weekday sessions. Sessions 0-19 are quiet (fill the 14-session
    RVOL/ATR windows). From session 20 on, two rotating names each day open
    on ~7x volume with a clean upside breakout; the rest stay quiet."""
    days = _weekdays(40)
    bars: dict[str, list[Bar]] = {s: [] for s in UNIVERSE}
    for i, day in enumerate(days):
        level = 200.0 + (i % 5) - 2.0  # gentle wander so ATR > 0
        spikers = set()
        if i >= 20:
            spikers = {UNIVERSE[i % len(UNIVERSE)], UNIVERSE[(i + 3) % len(UNIVERSE)]}
        for s in UNIVERSE:
            if s in spikers:
                bars[s] += _day_bars(
                    s, day, level=level, or_open=level, or_close=level + 0.8,
                    or_vol=780_000.0, post_close=level + 3.0, post_vol=320_000.0,
                )
            else:
                bars[s] += _day_bars(
                    s, day, level=level, or_open=level, or_close=level + 0.25,
                    or_vol=110_000.0, post_close=level + 0.4, post_vol=300_000.0,
                )
    return bars


def _params(**over):
    p = dict(OpeningBreakoutUSStrategy.presets()["balanced"])
    p.update(
        opening_range_minutes=5, rvol_lookback=14, atr_period=14, rvol_min=1.5, top_n=3,
        min_open_price=50.0, min_avg_daily_volume=300_000.0, min_atr=0.4,
        square_off_time="15:20", allow_short=True,
        sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
        capital_allocation=5_000_000.0, max_position_size_pct=20.0,
    )
    p.update(over)
    return OpeningBreakoutUSStrategy.resolve_params(p)


def test_opening_breakout_us_backtest_flows_end_to_end(capsys):
    candles = _dataset()

    dq = validate_candles(candles)
    assert dq["ok"], dq["errors"]

    total_bars = sum(len(v) for v in candles.values())
    engine = BacktestEngine(
        OpeningBreakoutUSStrategy, _params(), initial_capital=5_000_000.0,
        cost_model=CostModel(CostConfig()),
    )
    result = engine.run(candles)

    assert result.fills, "expected the strategy to trade on the high-RVOL breakout days"
    assert len(result.equity_curve) == total_bars
    assert result.total_costs > 0, "Indian cost model should charge every fill"

    traded_syms = {f.instrument for f in result.fills}
    assert len(traded_syms) >= 3, f"expected several instruments to trade, got {traded_syms}"

    # every entry must be matched by a same-day square-off (nothing overnight)
    assert all(q == 0 for q in result.final_positions.values()), result.final_positions

    mark = {s: b[-1].close for s, b in candles.items() if b}
    trades = reconstruct_trades(result.fills, fill_costs=[f.cost for f in result.fills],
                                mark_prices=mark)
    perf = compute_performance(result.equity_curve, trades, initial_capital=5_000_000.0,
                               total_costs=result.total_costs)
    for key in ("return_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                "calmar_ratio", "win_rate_pct", "profit_factor", "total_trades",
                "avg_trade", "turnover_ratio"):
        assert key in perf

    with capsys.disabled():
        print(
            f"\n[opening breakout US] {len(UNIVERSE)} instruments, {total_bars} bars, "
            f"{len(result.fills)} fills, {perf['total_trades']} closed trades\n"
            f"  net P&L {perf['net_pnl']:.0f}  return {perf['return_pct']:.2f}%  "
            f"costs {result.total_costs:.0f}  win% {perf['win_rate_pct']:.1f}  "
            f"maxDD {perf['max_drawdown_pct']:.2f}%  traded {sorted(traded_syms)}"
        )


def test_opening_breakout_us_backtest_zero_cost_beats_costed_run():
    """Sanity: identical run priced with zero charges keeps more P&L than the
    fully-costed run — confirms the cost model is actually being applied."""
    candles = _dataset()
    p = _params()

    costed = BacktestEngine(OpeningBreakoutUSStrategy, p, 5_000_000.0,
                            cost_model=CostModel(CostConfig())).run(candles)
    free = BacktestEngine(
        OpeningBreakoutUSStrategy, p, 5_000_000.0,
        cost_model=CostModel(CostConfig(
            brokerage_flat=0.0, brokerage_pct=0.0, stt_delivery_buy=0.0, stt_delivery_sell=0.0,
            stt_intraday_sell=0.0, exch_txn_equity=0.0, sebi_fee=0.0, stamp_intraday_buy=0.0,
            gst_rate=0.0, slippage_bps=0.0,
        )),
    ).run(candles)

    assert free.total_costs == 0.0
    assert costed.total_costs > 0.0
    assert free.equity_curve[-1][1] > costed.equity_curve[-1][1]

"""End-to-end backtest of the `multi-factor` template.

Real BacktestEngine + Indian CostModel over a deterministic multi-name
daily dataset, checking the full pipeline and that the book rotates into
the higher-scoring names.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.performance import build_charts, compute_performance
from app.backtesting.trades import reconstruct_trades
from app.strategies.base import Bar
from app.strategies.library import MultiFactorStrategy

IST = "+05:30"
UNIVERSE = [f"N{i:02d}" for i in range(8)]


def _days(n: int, start=date(2024, 1, 1)) -> list[date]:
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _dataset() -> dict[str, list[Bar]]:
    rng = random.Random(42)
    days = _days(320)
    # persistent per-name drift: first names strong, last names weak
    drift = {s: 0.0009 * (len(UNIVERSE) - 2 * i) for i, s in enumerate(UNIVERSE)}
    px = dict.fromkeys(UNIVERSE, 500.0)
    out: dict[str, list[Bar]] = {s: [] for s in UNIVERSE}
    for d in days:
        ts = datetime(d.year, d.month, d.day).strftime("%Y-%m-%dT00:00:00") + IST
        for s in UNIVERSE:
            px[s] *= 1 + drift[s] + rng.uniform(-0.012, 0.012)
            p = max(1.0, px[s])
            out[s].append(Bar(timestamp=ts, open=p, high=p * 1.01, low=p * 0.99,
                              close=p, volume=3_000_000.0, instrument=s))
    return out


def _params(**over):
    p = dict(MultiFactorStrategy.presets()["balanced"])
    p.update(
        mom_lookback_short=21, mom_lookback_mid=63, mom_lookback_long=126, mom_skip_recent=5,
        volatility_lookback=42, trend_quality_lookback=63, liquidity_lookback=21,
        num_long_positions=3, num_short_positions=0, allow_short=False,
        rebalance_frequency="monthly", weighting="equal_weight",
        min_avg_turnover=0.0, min_history_bars=0, max_volatility_pct=5000.0,
        capital_allocation=2_000_000.0, max_position_size_pct=40.0, product="CNC",
    )
    p.update(over)
    return MultiFactorStrategy.resolve_params(p)


def test_multi_factor_backtest_flows_end_to_end(capsys):
    candles = _dataset()
    dq = validate_candles(candles)
    assert dq["ok"], dq["errors"]

    total_bars = sum(len(v) for v in candles.values())
    engine = BacktestEngine(
        MultiFactorStrategy, _params(), initial_capital=2_000_000.0,
        cost_model=CostModel(CostConfig()),
    )
    result = engine.run(candles)

    assert result.fills, "expected the monthly rebalance to trade"
    assert len(result.equity_curve) == total_bars
    assert result.total_costs > 0

    traded = {f.instrument for f in result.fills}
    # the strongest-drift names should get bought at least once
    assert traded & {"N00", "N01", "N02"}

    mark = {s: float(b[-1].close) for s, b in candles.items() if b}
    trades = reconstruct_trades(result.fills, fill_costs=[f.cost for f in result.fills],
                                mark_prices=mark)
    perf = compute_performance(result.equity_curve, trades, initial_capital=2_000_000.0,
                               total_costs=result.total_costs, trading_days_per_year=252)
    charts = build_charts(result.equity_curve, trades, 2_000_000.0)
    for key in ("return_pct", "sharpe_ratio", "max_drawdown_pct", "turnover_ratio",
                "total_trades", "win_rate_pct"):
        assert key in perf
    assert "monthly_returns" in charts

    with capsys.disabled():
        print(
            f"\n[multi-factor] {len(UNIVERSE)} names, {total_bars} bars, "
            f"{len(result.fills)} fills, {perf['total_trades']} closed trades, "
            f"traded {sorted(traded)}  ret {perf['return_pct']:.2f}%"
        )


def test_multi_factor_long_only_never_shorts_when_disabled():
    candles = _dataset()
    result = BacktestEngine(
        MultiFactorStrategy, _params(allow_short=False), initial_capital=2_000_000.0,
        cost_model=CostModel(CostConfig()),
    ).run(candles)
    assert all(q >= 0 for q in result.final_positions.values())

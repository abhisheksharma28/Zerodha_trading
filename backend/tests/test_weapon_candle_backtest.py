"""End-to-end backtest of the `weapon-candle` template."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.performance import build_charts, compute_performance
from app.backtesting.trades import reconstruct_trades
from app.strategies.base import Bar
from app.strategies.library import WeaponCandleStrategy

IST = "+05:30"


def _weekdays(n: int, start=date(2026, 1, 5)) -> list[date]:
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _dataset() -> dict[str, list[Bar]]:
    rng = random.Random(20)
    days = _weekdays(220)
    out: dict[str, list[Bar]] = {}
    for sym in ("AAA", "BBB"):
        px = 500.0
        bars = []
        for i, d in enumerate(days):
            # regime: 40-bar down legs then 40-bar up legs -> EMA reclaims happen
            drift = -0.004 if (i // 40) % 2 == 0 else 0.006
            px *= 1 + drift + rng.uniform(-0.01, 0.01)
            p = max(1.0, px)
            ts = datetime(d.year, d.month, d.day).strftime("%Y-%m-%dT00:00:00") + IST
            bars.append(Bar(timestamp=ts, open=p, high=p * 1.012, low=p * 0.988,
                            close=p, volume=250_000.0, instrument=sym))
        out[sym] = bars
    return out


def _params(**over):
    p = dict(WeaponCandleStrategy.presets()["aggressive"])
    p.update(mode="classic", allow_short=False, trailing_atr_mult=2.5, atr_period=14,
             sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
             capital_allocation=1_000_000.0, max_position_size_pct=30.0, product="CNC")
    p.update(over)
    return WeaponCandleStrategy.resolve_params(p)


def test_weapon_candle_backtest_flows_end_to_end(capsys):
    candles = _dataset()
    dq = validate_candles(candles)
    assert dq["ok"], dq["errors"]

    total_bars = sum(len(v) for v in candles.values())
    res = BacktestEngine(
        WeaponCandleStrategy, _params(), initial_capital=1_000_000.0,
        cost_model=CostModel(CostConfig()), max_gross_exposure=4.0,
    ).run(candles)

    assert res.fills, "expected weapon-candle entries over the regime dataset"
    assert len(res.equity_curve) == total_bars
    assert res.total_costs > 0
    assert all(q >= 0 for q in res.final_positions.values())  # long-only

    mark = {s: float(b[-1].close) for s, b in candles.items() if b}
    trades = reconstruct_trades(res.fills, fill_costs=[f.cost for f in res.fills], mark_prices=mark)
    perf = compute_performance(res.equity_curve, trades, initial_capital=1_000_000.0,
                               total_costs=res.total_costs)
    charts = build_charts(res.equity_curve, trades, 1_000_000.0)
    for key in ("return_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades", "win_rate_pct"):
        assert key in perf
    assert "monthly_returns" in charts

    with capsys.disabled():
        print(f"\n[weapon candle] {total_bars} bars, {len(res.fills)} fills, "
              f"{perf['total_trades']} closed trades  ret {perf['return_pct']:.2f}%")


def test_weapon_candle_enhanced_mode_trades_less_than_classic():
    candles = _dataset()
    classic = BacktestEngine(WeaponCandleStrategy, _params(mode="classic"), 1_000_000.0,
                             cost_model=CostModel(CostConfig())).run(candles)
    enhanced = BacktestEngine(
        WeaponCandleStrategy,
        _params(mode="enhanced", alpha_score_min=70.0, use_vwap_align=False,
                use_volume_expansion=True, vol_expansion_mult=1.5),
        1_000_000.0, cost_model=CostModel(CostConfig()),
    ).run(candles)
    assert len(enhanced.fills) <= len(classic.fills)

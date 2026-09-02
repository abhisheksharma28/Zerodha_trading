"""Parameter-perturbation simulator."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.param_sim import run_param_sim
from app.strategies.base import Bar
from app.strategies.library import DonchianBreakoutStrategy


def _weekdays(n: int, start=date(2026, 1, 5)) -> list[date]:
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _dataset() -> dict[str, list[Bar]]:
    days = _weekdays(160)
    closes = [100 + (i % 3 - 1) for i in range(25)] + [100 + 2.0 * i for i in range(1, 30)]
    closes += [closes[-1] - 4 * i for i in range(1, 10)]
    closes += [closes[-1] + 1.5 * i for i in range(1, 40)]
    while len(closes) < 160:
        closes.append(closes[-1])
    out: dict[str, list[Bar]] = {}
    for sym in ("AAA", "BBB"):
        bars = []
        for i, d in enumerate(days):
            c = float(closes[i]) + (2.0 if sym == "BBB" else 0.0)
            ts = datetime(d.year, d.month, d.day).strftime("%Y-%m-%dT00:00:00") + "+05:30"
            bars.append(Bar(timestamp=ts, open=c, high=c + 1.5, low=c - 1.5, close=c,
                            volume=200_000.0, instrument=sym))
        out[sym] = bars
    return out


def _params(**over):
    p = dict(DonchianBreakoutStrategy.presets()["balanced"])
    p.update(entry_period=20, exit_period=10, atr_period=14, atr_stop_mult=2.0,
             trailing_atr_mult=0.0, rvol_min=0.0, adx_min=0.0, atr_expansion_min=0.0,
             sizing_method="fixed_quantity", fixed_quantity=10, capital_allocation=1_000_000.0)
    p.update(over)
    return DonchianBreakoutStrategy.resolve_params(p)


def test_param_sim_is_deterministic_and_well_shaped():
    candles = _dataset()
    a = run_param_sim(DonchianBreakoutStrategy, _params(), candles, initial_capital=1_000_000.0,
                      cost_model=CostModel(CostConfig()), n_samples=12, seed=3, pct=5.0)
    b = run_param_sim(DonchianBreakoutStrategy, _params(), candles, initial_capital=1_000_000.0,
                      cost_model=CostModel(CostConfig()), n_samples=12, seed=3, pct=5.0)
    assert a == b
    assert a["n_samples"] == 12
    assert "entry_period" in a["perturbed_params"]
    assert "capital_allocation" not in a["perturbed_params"]
    for kpi in ("return_pct", "sharpe_ratio", "max_drawdown_pct"):
        d = a["distribution"][kpi]
        assert d["min"] <= d["p50"] <= d["max"]
    assert a["verdict"] in ("stable", "fragile")
    assert isinstance(a["base"]["sharpe_ratio"], float)


def test_param_sim_perturbs_within_the_band():
    candles = _dataset()
    # entry_period=20 -> +/-5% keeps integer draws in [19, 21]
    seen: set[int] = set()
    import app.backtesting.param_sim as ps

    orig = ps.BacktestEngine

    class _Spy(orig):  # capture the entry_period each run sees
        def __init__(self, cls, params, cap, **kw):
            seen.add(int(params["entry_period"]))
            super().__init__(cls, params, cap, **kw)

    ps.BacktestEngine = _Spy
    try:
        run_param_sim(DonchianBreakoutStrategy, _params(entry_period=20), candles,
                      initial_capital=1_000_000.0, n_samples=40, seed=1, pct=5.0)
    finally:
        ps.BacktestEngine = orig
    assert seen <= {19, 20, 21}, seen

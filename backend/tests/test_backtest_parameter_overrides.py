"""Per-run parameter overrides (e.g. a fixed quantity) in the backtest tab.

Covers merge_parameter_overrides directly and an end-to-end BacktestEngine
run showing a fixed-quantity override actually changes the fills — without
a DB or broker.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.engine import BacktestEngine
from app.core.exceptions import ValidationError
from app.services.backtest_service import merge_parameter_overrides
from app.strategies.base import Bar
from app.strategies.library import DonchianBreakoutStrategy


def _base() -> dict:
    return DonchianBreakoutStrategy.resolve_params(DonchianBreakoutStrategy.presets()["balanced"])


def test_merge_applies_and_validates_overrides():
    merged = merge_parameter_overrides(
        DonchianBreakoutStrategy, _base(),
        {"sizing_method": "fixed_quantity", "fixed_quantity": 50},
    )
    assert merged["sizing_method"] == "fixed_quantity"
    assert merged["fixed_quantity"] == 50
    # untouched keys survive
    assert merged["entry_period"] == _base()["entry_period"]


def test_merge_rejects_unknown_key():
    with pytest.raises(ValidationError):
        merge_parameter_overrides(DonchianBreakoutStrategy, _base(), {"bogus_param": 1})


def test_merge_rejects_out_of_range_value():
    with pytest.raises(ValidationError):
        merge_parameter_overrides(
            DonchianBreakoutStrategy, _base(), {"risk_per_trade_pct": 999_999}
        )


def test_merge_noop_without_overrides_returns_base():
    b = _base()
    assert merge_parameter_overrides(DonchianBreakoutStrategy, b, {}) == b


def _weekdays(n: int, start=date(2026, 1, 5)) -> list[date]:
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _bars(sym: str) -> list[Bar]:
    days = _weekdays(60)
    closes = [100 + (i % 3 - 1) for i in range(25)] + [100 + 2.5 * i for i in range(1, 26)] + [
        160 - 6 * i for i in range(1, 10)
    ]
    out = []
    for d, c in zip(days, [float(x) for x in closes], strict=False):
        ts = datetime(d.year, d.month, d.day).strftime("%Y-%m-%dT00:00:00") + "+05:30"
        out.append(Bar(timestamp=ts, open=c, high=c + 1.5, low=c - 1.5, close=c,
                       volume=200_000.0, instrument=sym))
    return out


def test_fixed_quantity_override_changes_fills_end_to_end():
    candles = {"INFY": _bars("INFY")}
    params = merge_parameter_overrides(
        DonchianBreakoutStrategy, _base(),
        {"sizing_method": "fixed_quantity", "fixed_quantity": 7, "trailing_atr_mult": 0.0},
    )
    res = BacktestEngine(DonchianBreakoutStrategy, params, 1_000_000.0,
                         cost_model=CostModel(CostConfig())).run(candles)
    assert res.fills, "expected a breakout entry"
    assert {f.quantity for f in res.fills} == {7}

"""Behavioural tests for the five strategy templates.

Pure unit tests: each template is exercised directly with synthetic bars
through a fake context that mimics how the backtest engine fills orders
(immediately, at the bar close). No database, no broker.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.strategies.base import Bar, StrategyContext
from app.strategies.library import (
    TEMPLATES,
    CrossSectionalMomentumStrategy,
    MeanReversionStrategy,
    OpeningRangeBreakoutStrategy,
    PairsTradingStrategy,
    TrendFollowingStrategy,
)
from app.strategies.library.base import ParamError

IST_OFFSET = "+05:30"


def _bar(sym: str, close: float, ts: str, *, vol: float = 100_000.0,
         high: float | None = None, low: float | None = None) -> Bar:
    return Bar(
        timestamp=ts,
        open=close,
        high=high if high is not None else close * 1.002,
        low=low if low is not None else close * 0.998,
        close=close,
        volume=vol,
        instrument=sym,
    )


def run(strategy_cls, params: dict, steps: list[Bar]):
    """Feed bars one at a time. Returns a list of (step_index, [OrderRequest]).

    Between steps we update ``context.positions`` from the drained orders,
    exactly as the backtest engine does with fill-at-close.
    """
    ctx = StrategyContext(parameters=params)
    strat = strategy_cls(ctx)
    strat.on_start()
    positions: dict[str, int] = {}
    emitted: list[tuple[int, list]] = []
    for i, bar in enumerate(steps):
        ctx.positions = dict(positions)
        strat.on_bar(bar)
        orders = ctx.drain_pending_orders()
        if orders:
            emitted.append((i, orders))
            for o in orders:
                signed = o.quantity if o.transaction_type == "BUY" else -o.quantity
                positions[o.tradingsymbol] = positions.get(o.tradingsymbol, 0) + signed
    strat.on_stop()
    return emitted, positions


def daily_ts(i: int, start=datetime(2026, 1, 1)) -> str:
    return (start + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00") + IST_OFFSET


def intraday_ts(day: datetime, minute_offset: int) -> str:
    return (day + timedelta(minutes=minute_offset)).strftime("%Y-%m-%dT%H:%M:00") + IST_OFFSET


# --------------------------------------------------------------------------
# schema / presets
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cls", TEMPLATES, ids=[t.SLUG for t in TEMPLATES])
def test_metadata_and_schema_wellformed(cls):
    md = cls.METADATA
    assert md.slug == cls.SLUG and md.name == cls.NAME
    assert md.warning  # every template carries a research warning
    schema = cls.parameter_schema()
    assert schema and all("type" in s and "default" in s for s in schema.values())


@pytest.mark.parametrize("cls", TEMPLATES, ids=[t.SLUG for t in TEMPLATES])
def test_all_presets_validate(cls):
    for name, preset in cls.presets().items():
        resolved = cls.resolve_params(preset)
        assert set(resolved) == set(cls.all_params()), name


@pytest.mark.parametrize("cls", TEMPLATES, ids=[t.SLUG for t in TEMPLATES])
def test_param_validation_rejects_bad_input(cls):
    with pytest.raises(ParamError):
        cls.resolve_params({"definitely_not_a_param": 1})
    with pytest.raises(ParamError):
        cls.resolve_params({"capital_allocation": -5})


# --------------------------------------------------------------------------
# trend following
# --------------------------------------------------------------------------

def _trend_params(**over):
    p = dict(TrendFollowingStrategy.presets()["balanced"])
    p.update(ma_type="sma", fast_period=5, slow_period=15, atr_period=5,
             trend_strength_min_pct=0.0, vol_min_pct=0.0, vol_max_pct=1000.0,
             trailing_atr_mult=0.0, take_profit_pct=0.0, sizing_method="fixed_quantity",
             fixed_quantity=10, regime_filter_enabled=False)
    p.update(over)
    return TrendFollowingStrategy.resolve_params(p)


def test_trend_following_enters_long_on_bullish_crossover():
    # 25 flat bars, then a sustained rise -> fast MA crosses above slow MA.
    closes = [100.0] * 25 + [100 + 3 * i for i in range(1, 25)]
    bars = [_bar("INFY", c, daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(TrendFollowingStrategy, _trend_params(), bars)
    assert emitted, "expected at least one order"
    _, first_orders = emitted[0]
    assert first_orders[0].transaction_type == "BUY"
    assert positions["INFY"] > 0


def test_trend_following_exits_on_opposite_crossover():
    closes = (
        [100.0] * 25
        + [100 + 3 * i for i in range(1, 25)]     # uptrend -> long
        + [172 - 4 * i for i in range(1, 30)]     # downtrend -> opposite cross
    )
    bars = [_bar("INFY", c, daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(TrendFollowingStrategy, _trend_params(atr_stop_mult=0.0), bars)
    sides = [o.transaction_type for _, orders in emitted for o in orders]
    assert "BUY" in sides and "SELL" in sides
    assert positions.get("INFY", 0) == 0  # flat again after the downtrend


def test_trend_following_atr_stop_forces_exit():
    closes = [100.0] * 25 + [100 + 3 * i for i in range(1, 16)]  # long entry established
    closes += [closes[-1] * 0.55]  # deep one-bar crash well below entry -> ATR stop fires
    bars = [_bar("INFY", c, daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(TrendFollowingStrategy, _trend_params(atr_stop_mult=2.0), bars)
    assert emitted, "expected an entry before the crash"
    assert positions.get("INFY", 0) == 0
    assert emitted[-1][1][-1].transaction_type == "SELL"


# --------------------------------------------------------------------------
# mean reversion
# --------------------------------------------------------------------------

def _mr_params(**over):
    p = dict(MeanReversionStrategy.presets()["balanced"])
    p.update(lookback=20, entry_zscore=2.0, exit_zscore=0.0, stop_zscore=4.0,
             regime_filter_enabled=False, sizing_method="fixed_quantity", fixed_quantity=7,
             max_holding_bars=0, min_volume=0.0)
    p.update(over)
    return MeanReversionStrategy.resolve_params(p)


def test_mean_reversion_buys_the_dip_and_exits_on_reversion():
    closes = [100.0] * 25 + [88.0]      # sharp drop -> z well below -2
    closes += [100.0]                    # snap back to mean -> z >= 0 -> exit
    bars = [_bar("SBIN", c, daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(MeanReversionStrategy, _mr_params(), bars)
    sides = [(step, o.transaction_type) for step, orders in emitted for o in orders]
    assert sides[0][1] == "BUY" and sides[0][0] == 25
    assert positions.get("SBIN", 0) == 0


def test_mean_reversion_stop_zscore_exits_when_it_keeps_falling():
    closes = [100.0] * 25 + [90.0, 80.0, 70.0, 60.0]  # keeps diverging past stop_zscore
    bars = [_bar("SBIN", c, daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(MeanReversionStrategy, _mr_params(stop_zscore=2.5), bars)
    assert positions.get("SBIN", 0) == 0
    assert any(o.transaction_type == "SELL" for _, orders in emitted for o in orders)


def test_mean_reversion_regime_filter_blocks_longs_in_downtrend():
    # benchmark trending hard down; target dips -> long would fire but regime blocks it.
    steps: list[Bar] = []
    for i in range(26):
        steps.append(_bar("NIFTY 50", 100.0 - i, daily_ts(i)))     # benchmark downtrend
        steps.append(_bar("SBIN", 100.0 if i < 25 else 85.0, daily_ts(i)))
    p = _mr_params(regime_filter_enabled=True, regime_benchmark="NIFTY 50",
                   regime_trend_lookback=10)
    emitted, positions = run(MeanReversionStrategy, p, steps)
    assert positions.get("SBIN", 0) == 0  # long entry suppressed by the regime filter


# --------------------------------------------------------------------------
# cross-sectional momentum
# --------------------------------------------------------------------------

def test_momentum_longs_the_strongest_names_on_rebalance():
    names = ["AAA", "BBB", "CCC", "DDD"]
    slopes = {"AAA": 2.0, "BBB": 1.0, "CCC": 0.2, "DDD": -1.0}  # AAA strongest
    steps: list[Bar] = []
    for day in range(160):
        for n in names:
            price = max(1.0, 500.0 + slopes[n] * day)
            steps.append(_bar(n, price, daily_ts(day), vol=1_000_000))
    params = CrossSectionalMomentumStrategy.resolve_params({
        **CrossSectionalMomentumStrategy.presets()["balanced"],
        "lookback_1": 20, "lookback_2": 40, "lookback_3": 120,
        "num_long_positions": 2, "num_short_positions": 0, "allow_short": False,
        "rebalance_frequency": "monthly", "min_avg_volume": 0.0, "min_history_bars": 0,
        "capital_allocation": 1_000_000.0,
    })
    emitted, positions = run(CrossSectionalMomentumStrategy, params, steps)
    assert emitted, "expected a rebalance to fire"
    longs = {s for s, q in positions.items() if q > 0}
    assert "AAA" in longs and "DDD" not in longs
    assert all(q >= 0 for q in positions.values())  # long-only


# --------------------------------------------------------------------------
# opening range breakout
# --------------------------------------------------------------------------

def _orb_params(**over):
    p = dict(OpeningRangeBreakoutStrategy.presets()["balanced"])
    p.update(opening_range_start="09:15", opening_range_end="09:30", square_off_time="15:15",
             volume_multiplier=1.0, use_vwap_filter=False, market_trend_filter=False,
             atr_stop_mult=0.0, stop_loss_pct=1.0, target_pct=0.0, trailing_stop_pct=0.0,
             allow_short=False, sizing_method="fixed_quantity", fixed_quantity=5,
             max_trades_per_day=2, max_daily_loss_pct=0.0)
    p.update(over)
    return OpeningRangeBreakoutStrategy.resolve_params(p)


def test_orb_breaks_out_above_opening_range_then_squares_off():
    day = datetime(2026, 3, 3, 9, 15)  # a Tuesday
    steps: list[Bar] = []
    # opening range 09:15-09:30 in 5-min bars: high ~101, low ~99
    for k, px in enumerate([100.0, 101.0, 99.0]):
        steps.append(_bar("RELIANCE", px, intraday_ts(day, 5 * k), vol=10_000,
                          high=px + 0.5, low=px - 0.5))
    # 09:35 bar breaks above OR high on strong volume
    steps.append(_bar("RELIANCE", 102.5, intraday_ts(day, 20), vol=100_000,
                      high=103.0, low=101.5))
    # drift, then a bar after square-off time
    steps.append(_bar("RELIANCE", 103.0, intraday_ts(day, 60), vol=20_000))
    steps.append(_bar("RELIANCE", 103.5, intraday_ts(day, 6 * 60 + 5), vol=20_000))  # 15:20
    emitted, positions = run(OpeningRangeBreakoutStrategy, _orb_params(), steps)
    sides = [o.transaction_type for _, orders in emitted for o in orders]
    assert sides[0] == "BUY"
    assert positions.get("RELIANCE", 0) == 0  # squared off by 15:15


def test_orb_respects_daily_trade_cap():
    day = datetime(2026, 3, 3, 9, 15)
    steps = []
    for k, px in enumerate([100.0, 101.0, 99.0]):
        steps.append(_bar("RELIANCE", px, intraday_ts(day, 5 * k), vol=10_000,
                          high=px + 0.5, low=px - 0.5))
    # many breakout + fail cycles; cap is 1 long/day
    seq = [102.5, 100.5, 102.9, 100.4, 103.2, 100.3]
    for k, px in enumerate(seq):
        steps.append(_bar("RELIANCE", px, intraday_ts(day, 20 + 5 * k), vol=100_000,
                          high=px + 1, low=px - 1))
    emitted, _ = run(OpeningRangeBreakoutStrategy, _orb_params(max_long_trades_per_day=1,
                                                              stop_loss_pct=0.3), steps)
    buys = [1 for _, orders in emitted for o in orders if o.transaction_type == "BUY"]
    assert sum(buys) == 1


# --------------------------------------------------------------------------
# pairs trading
# --------------------------------------------------------------------------

def test_pairs_opens_and_closes_a_market_neutral_spread():
    import random

    random.seed(5)
    steps: list[Bar] = []
    base = 100.0
    for i in range(140):
        base *= 1 + random.uniform(-0.01, 0.01)      # common factor; legs perfectly coupled
        steps.append(_bar("HDFCBANK", base, daily_ts(i)))
        steps.append(_bar("ICICIBANK", base, daily_ts(i)))
    # push A above / B below their shared level -> spread Z spikes positive
    for k, i in enumerate(range(140, 150)):
        steps.append(_bar("HDFCBANK", base + 2.0 + k * 0.5, daily_ts(i)))
        steps.append(_bar("ICICIBANK", base - 1.0, daily_ts(i)))
    # converge back to the shared level -> Z returns toward 0 -> exit
    for i in range(150, 170):
        steps.append(_bar("HDFCBANK", base, daily_ts(i)))
        steps.append(_bar("ICICIBANK", base, daily_ts(i)))
    params = PairsTradingStrategy.resolve_params({
        **PairsTradingStrategy.presets()["balanced"],
        "lookback": 30, "regression_window": 30, "entry_zscore": 1.8, "exit_zscore": 0.3,
        "stop_zscore": 8.0, "require_cointegration": False, "capital_allocation": 1_000_000.0,
        "max_position_size_pct": 25.0, "cointegration_lookback": 120,
    })
    emitted, positions = run(PairsTradingStrategy, params, steps)
    all_orders = [o for _, orders in emitted for o in orders]
    syms = {o.tradingsymbol for o in all_orders}
    assert syms == {"HDFCBANK", "ICICIBANK"}, "both legs must trade"
    # opening trade shorts the rich leg (A) and buys the cheap leg (B)
    first = {o.tradingsymbol: o.transaction_type for o in emitted[0][1]}
    assert first["HDFCBANK"] == "SELL" and first["ICICIBANK"] == "BUY"
    assert positions.get("HDFCBANK", 0) == 0 and positions.get("ICICIBANK", 0) == 0


def test_pairs_cointegration_gate_blocks_a_non_stationary_spread():
    import random

    random.seed(3)
    steps = []
    a, b = 100.0, 100.0
    for i in range(300):
        a += random.gauss(0, 1)          # independent random walks -> not cointegrated
        b += random.gauss(0, 1)
        steps.append(_bar("X", abs(a) + 50, daily_ts(i)))
        steps.append(_bar("Y", abs(b) + 50, daily_ts(i)))
    params = PairsTradingStrategy.resolve_params({
        **PairsTradingStrategy.presets()["balanced"],
        "lookback": 30, "regression_window": 30, "entry_zscore": 1.0,
        "require_cointegration": True, "adf_threshold": -3.5, "cointegration_lookback": 250,
    })
    emitted, _ = run(PairsTradingStrategy, params, steps)
    assert emitted == []  # gate refuses every entry


# --------------------------------------------------------------------------
# look-ahead bias + determinism
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls, params_fn, sym",
    [
        (TrendFollowingStrategy, _trend_params, "INFY"),
        (MeanReversionStrategy, _mr_params, "SBIN"),
    ],
    ids=["trend-following", "mean-reversion"],
)
def test_no_lookahead_future_bars_cannot_change_past_signals(cls, params_fn, sym):
    import random

    random.seed(11)
    closes = []
    px = 100.0
    for _ in range(120):
        px *= 1 + random.uniform(-0.03, 0.03)
        closes.append(round(px, 2))
    bars = [_bar(sym, c, daily_ts(i)) for i, c in enumerate(closes)]

    cutoff = 90
    short_run, _ = run(cls, params_fn(), bars[:cutoff])
    long_run, _ = run(cls, params_fn(), bars[: cutoff + 25])
    long_run_truncated = [(i, o) for (i, o) in long_run if i < cutoff]

    def norm(runs):
        return [
            (i, [(o.tradingsymbol, o.transaction_type, o.quantity) for o in orders])
            for i, orders in runs
        ]

    assert norm(short_run) == norm(long_run_truncated)


@pytest.mark.parametrize("cls", TEMPLATES, ids=[t.SLUG for t in TEMPLATES])
def test_deterministic_same_input_same_output(cls):
    import random

    random.seed(cls.SLUG.__hash__() & 0xFFFF)
    n_instr = max(cls.MIN_INSTRUMENTS, 1)
    syms = [f"S{i}" for i in range(n_instr)] + ["NIFTY 50"]
    prices = dict.fromkeys(syms, 100.0)
    steps = []
    for day in range(200):
        for s in syms:
            prices[s] *= 1 + random.uniform(-0.02, 0.021)
            steps.append(_bar(s, round(prices[s], 2), daily_ts(day)))

    params = cls.resolve_params(cls.presets()["balanced"])
    run1 = run(cls, dict(params), [_bar(b.instrument, b.close, b.timestamp, vol=b.volume,
                                        high=b.high, low=b.low) for b in steps])
    run2 = run(cls, dict(params), [_bar(b.instrument, b.close, b.timestamp, vol=b.volume,
                                        high=b.high, low=b.low) for b in steps])

    def norm(res):
        emitted, positions = res
        return (
            [(i, [(o.tradingsymbol, o.transaction_type, o.quantity) for o in orders])
             for i, orders in emitted],
            positions,
        )

    assert norm(run1) == norm(run2)

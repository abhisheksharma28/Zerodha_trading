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
    DonchianBreakoutStrategy,
    IndexFuturesArbitrageStrategy,
    LatencyArbitrageStrategy,
    MeanReversionStrategy,
    MultiFactorStrategy,
    OpeningBreakoutUSStrategy,
    OpeningRangeBreakoutStrategy,
    PairsTradingStrategy,
    RegimeAdaptiveStrategy,
    TrendFollowingStrategy,
    VolatilityRegimeStrategy,
    WeaponCandleStrategy,
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
# donchian breakout
# --------------------------------------------------------------------------

def _donchian_params(**over):
    p = dict(DonchianBreakoutStrategy.presets()["balanced"])
    p.update(entry_period=20, exit_period=10, breakout_on="close", allow_short=False,
             atr_period=5, atr_stop_mult=2.0, trailing_atr_mult=0.0, max_holding_bars=0,
             rvol_min=0.0, atr_expansion_min=0.0, adx_min=0.0, regime_filter_enabled=False,
             sizing_method="fixed_quantity", fixed_quantity=10)
    p.update(over)
    return DonchianBreakoutStrategy.resolve_params(p)


def test_donchian_enters_long_on_channel_breakout():
    # 30 bars ranging 99-101, then a decisive close above the 20-bar high.
    closes = [100 + (i % 3 - 1) for i in range(30)] + [108.0]
    bars = [_bar("INFY", float(c), daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(DonchianBreakoutStrategy, _donchian_params(), bars)
    assert emitted, "expected a breakout entry"
    assert emitted[-1][1][0].transaction_type == "BUY"
    assert positions.get("INFY", 0) == 10


def test_donchian_exits_on_opposite_channel():
    closes = [100 + (i % 3 - 1) for i in range(30)] + [108.0, 109.0, 110.0]
    closes += [92.0]  # decisive close below the 10-bar low -> channel exit
    bars = [_bar("INFY", float(c), daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(DonchianBreakoutStrategy, _donchian_params(atr_stop_mult=0.0), bars)
    assert emitted and emitted[-1][1][-1].transaction_type == "SELL"
    assert positions.get("INFY", 0) == 0


def test_donchian_atr_stop_forces_exit():
    closes = [100 + (i % 3 - 1) for i in range(30)] + [108.0, 109.0]
    closes += [95.0]  # sharp drop below entry - 2*ATR
    bars = [_bar("INFY", float(c), daily_ts(i)) for i, c in enumerate(closes)]
    emitted, positions = run(DonchianBreakoutStrategy, _donchian_params(atr_stop_mult=2.0), bars)
    assert emitted and positions.get("INFY", 0) == 0
    assert emitted[-1][1][-1].transaction_type == "SELL"


def test_donchian_rvol_filter_blocks_a_thin_breakout():
    closes = [100 + (i % 3 - 1) for i in range(30)] + [108.0]
    # breakout bar has only 10% of the recent average volume
    bars = [
        _bar("INFY", float(c), daily_ts(i), vol=100_000.0 if i < 30 else 10_000.0)
        for i, c in enumerate(closes)
    ]
    emitted, _ = run(DonchianBreakoutStrategy, _donchian_params(rvol_min=1.5), bars)
    assert not emitted, "thin-volume breakout should be filtered out"


# --------------------------------------------------------------------------
# weapon candle
# --------------------------------------------------------------------------

def _weapon_params(**over):
    p = dict(WeaponCandleStrategy.presets()["aggressive"])  # classic mode, no filters
    p.update(mode="classic", require_prev_below=True, allow_short=False, arm_expiry_bars=3,
             ema_period=9, macd_fast=6, macd_slow=13, macd_signal=5, atr_stop_mult=0.0,
             trailing_atr_mult=0.0, take_profit_r=0.0, max_holding_bars=0, product="CNC",
             regime_filter_enabled=False, sizing_method="fixed_quantity", fixed_quantity=10)
    p.update(over)
    return WeaponCandleStrategy.resolve_params(p)


def _weapon_bars(closes: list[float]) -> list[Bar]:
    # give each bar a high/low a touch beyond the close so break/stop logic has room
    out = []
    for i, c in enumerate(closes):
        hi = c + 1.0
        lo = c - 1.0
        out.append(_bar("INFY", float(c), daily_ts(i), high=hi, low=lo))
    return out


def test_weapon_candle_enters_on_break_of_the_reclaim_bar():
    # 30 bars sliding DOWN (price + MACD below EMA9), then a sharp reclaim bar,
    # then a bar that takes out the reclaim bar's high -> entry.
    closes = [100 - i for i in range(30)] + [92.0, 120.0, 121.0, 122.0]
    emitted, positions = run(WeaponCandleStrategy, _weapon_params(), _weapon_bars(closes))
    assert emitted, "expected a weapon-candle breakout entry"
    assert emitted[-1][1][0].transaction_type == "BUY"
    assert positions.get("INFY", 0) == 10


def test_weapon_candle_stop_is_the_reclaim_bar_low():
    closes = [100 - i for i in range(30)] + [92.0, 120.0, 121.0]  # entry on the 121 bar
    closes += [90.0]  # collapses below the reclaim bar's low (~119) -> stop out
    emitted, positions = run(WeaponCandleStrategy, _weapon_params(), _weapon_bars(closes))
    assert emitted and positions.get("INFY", 0) == 0
    assert emitted[-1][1][-1].transaction_type == "SELL"


def test_weapon_candle_arm_expires_without_a_break():
    # reclaim bar closes 92 (high ~93); following bars stay well below that high
    closes = [100 - i for i in range(30)] + [92.0, 89.0, 89.0, 89.0, 89.0, 89.0]
    emitted, _ = run(WeaponCandleStrategy, _weapon_params(arm_expiry_bars=2), _weapon_bars(closes))
    assert not emitted, "arm should expire before any break"


def test_weapon_candle_enhanced_mode_blocks_low_alpha_signals():
    closes = [100 - i for i in range(30)] + [92.0, 120.0, 121.0, 122.0]
    p = _weapon_params(mode="enhanced", alpha_score_min=99.0, use_vwap_align=False,
                       use_volume_expansion=False)
    emitted, _ = run(WeaponCandleStrategy, p, _weapon_bars(closes))
    assert not emitted, "alpha score below threshold must block the entry"


# --------------------------------------------------------------------------
# volatility regime
# --------------------------------------------------------------------------

def _volreg_params(**over):
    p = dict(VolatilityRegimeStrategy.presets()["balanced"])
    p.update(mode="trend_only", allow_short=False, vol_lookback=10, vol_percentile_lookback=40,
             breakout_period=10, bollinger_period=10, trend_ma_period=15, trend_ma_type="sma",
             atr_period=5, atr_stop_mult=2.0, trailing_atr_mult=0.0, no_trade_in_extreme=True,
             regime_filter_enabled=False, sizing_method="fixed_quantity", fixed_quantity=10)
    p.update(over)
    return VolatilityRegimeStrategy.resolve_params(p)


def _wobble(base: list[float], amp: float, seed: int) -> list[Bar]:
    import random

    rng = random.Random(seed)
    out = []
    for i, c in enumerate(base):
        c2 = c + rng.uniform(-amp, amp)
        out.append(_bar("INFY", max(1.0, c2), daily_ts(i), high=c2 + amp + 1, low=c2 - amp - 1))
    return out


def test_volatility_regime_takes_a_trend_cross_in_calm_vol():
    # phase 1: noisy & flat (high vol history); phase 2: calm smooth ramp up
    base = [100.0] * 45 + [100 + 1.2 * i for i in range(25)]
    bars = _wobble(base[:45], 6.0, 1) + _wobble(base[45:], 0.3, 2)
    # fix instrument/time continuity
    bars = [
        _bar("INFY", b.close, daily_ts(i), high=b.high, low=b.low)
        for i, b in enumerate(bars)
    ]
    emitted, positions = run(VolatilityRegimeStrategy, _volreg_params(), bars)
    assert emitted, "expected a trend entry once vol calms and price crosses the MA"
    assert emitted[-1][1][0].transaction_type == "BUY"


def test_volatility_regime_blocks_entries_in_extreme_vol():
    # phase 1 calm, phase 2 very noisy ramp -> current vol percentile is EXTREME
    base = [100.0] * 45 + [100 + 1.2 * i for i in range(25)]
    bars = _wobble(base[:45], 0.3, 3) + _wobble(base[45:], 9.0, 4)
    bars = [_bar("INFY", b.close, daily_ts(i), high=b.high, low=b.low) for i, b in enumerate(bars)]
    emitted, _ = run(VolatilityRegimeStrategy, _volreg_params(no_trade_in_extreme=True), bars)
    emitted_off, _ = run(
        VolatilityRegimeStrategy, _volreg_params(no_trade_in_extreme=False), bars
    )
    assert len(emitted) <= len(emitted_off)


# --------------------------------------------------------------------------
# regime adaptive
# --------------------------------------------------------------------------

def _regime_params(**over):
    p = dict(RegimeAdaptiveStrategy.presets()["balanced"])
    p.update(benchmark_symbol="", adx_period=7, adx_trend_min=22.0, er_period=10,
             er_trend_min=0.35, slope_ma_period=15, slope_lookback=5, vol_lookback=10,
             vol_percentile_lookback=40, high_vol_pct=95.0, breakout_period=10,
             breakout_exit_period=5, mr_lookback=10, mr_entry_z=1.5, mr_exit_z=0.3,
             atr_period=5, atr_stop_mult=2.5, trailing_atr_mult=0.0, allow_short=False,
             exit_on_regime_flip=True, regime_filter_enabled=False,
             sizing_method="fixed_quantity", fixed_quantity=10)
    p.update(over)
    return RegimeAdaptiveStrategy.resolve_params(p)


def test_regime_adaptive_breaks_out_in_a_trend():
    closes = [100 + (i % 3 - 1) for i in range(25)] + [100 + 2.5 * i for i in range(1, 30)]
    bars = [_bar("INFY", float(c), daily_ts(i), high=c + 1, low=c - 1) for i, c in enumerate(closes)]
    emitted, positions = run(RegimeAdaptiveStrategy, _regime_params(trade_ranging=False), bars)
    assert emitted, "expected a trend breakout entry in the TRENDING regime"
    assert emitted[-1][1][0].transaction_type == "BUY"
    assert positions.get("INFY", 0) == 10


def test_regime_adaptive_mean_reverts_in_a_range():
    import math

    base = [100 + 4 * math.sin(i / 2.0) for i in range(55)]
    base += [82.0]  # sharp dip -> z well below -1.5 while regime is RANGING
    bars = [_bar("INFY", float(c), daily_ts(i), high=c + 1.2, low=c - 1.2)
            for i, c in enumerate(base)]
    emitted, positions = run(RegimeAdaptiveStrategy, _regime_params(trade_trending=False), bars)
    assert emitted, "expected a mean-reversion entry in the RANGING regime"
    sides = [o.transaction_type for _, orders in emitted for o in orders]
    assert sides[0] == "BUY", "first mean-reversion order should be a long on the dip"


def test_regime_adaptive_no_short_when_disabled():
    closes = [200 - 2.0 * i for i in range(55)]  # steady downtrend
    bars = [_bar("INFY", max(1.0, float(c)), daily_ts(i), high=c + 1, low=c - 1)
            for i, c in enumerate(closes)]
    _, positions = run(RegimeAdaptiveStrategy, _regime_params(allow_short=False), bars)
    assert all(q >= 0 for q in positions.values())


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
# multi-factor investing
# --------------------------------------------------------------------------

def _mf_params(**over):
    p = dict(MultiFactorStrategy.presets()["balanced"])
    p.update(
        mom_lookback_short=15, mom_lookback_mid=30, mom_lookback_long=55, mom_skip_recent=2,
        volatility_lookback=20, trend_quality_lookback=30, liquidity_lookback=10,
        weight_momentum=1.0, weight_low_volatility=0.0, weight_trend_quality=0.0,
        weight_liquidity=0.0, num_long_positions=2, num_short_positions=0, allow_short=False,
        weighting="equal_weight", rebalance_frequency="monthly", min_avg_turnover=0.0,
        min_history_bars=0, max_volatility_pct=5000.0, capital_allocation=1_000_000.0,
    )
    p.update(over)
    return MultiFactorStrategy.resolve_params(p)


def test_multi_factor_holds_top_ranked_names_on_rebalance():
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    slopes = {"AAA": 3.0, "BBB": 2.5, "CCC": 0.1, "DDD": 0.0, "EEE": -0.5, "FFF": -1.5}
    steps: list[Bar] = []
    for day in range(90):
        for n in names:
            steps.append(_bar(n, max(1.0, 500.0 + slopes[n] * day), daily_ts(day), vol=1_000_000))
    emitted, positions = run(MultiFactorStrategy, _mf_params(), steps)
    assert emitted, "expected a rebalance to fire"
    longs = {s for s, q in positions.items() if q > 0}
    assert longs == {"AAA", "BBB"}
    assert all(q >= 0 for q in positions.values())


def test_multi_factor_low_vol_weight_prefers_the_calm_name():
    import random

    random.seed(7)
    names = ["CALM", "WILD", "MID1", "MID2", "MID3"]
    steps: list[Bar] = []
    for day in range(90):
        for n in names:
            drift = 500.0 + 1.0 * day  # identical upward drift for all
            noise = {"CALM": 0.4, "WILD": 22.0, "MID1": 6.0, "MID2": 6.0, "MID3": 6.0}[n]
            px = max(1.0, drift + random.uniform(-noise, noise))
            steps.append(_bar(n, px, daily_ts(day), vol=1_000_000))
    params = _mf_params(weight_momentum=0.0, weight_low_volatility=1.0,
                        weight_trend_quality=0.0, num_long_positions=1)
    _, positions = run(MultiFactorStrategy, params, steps)
    longs = {s for s, q in positions.items() if q > 0}
    assert longs == {"CALM"}


def test_multi_factor_turnover_filter_excludes_thin_names():
    names = ["LIQ1", "LIQ2", "THIN"]
    steps: list[Bar] = []
    for day in range(90):
        for n in names:
            vol = 200.0 if n == "THIN" else 5_000_000.0
            steps.append(_bar(n, max(1.0, 500.0 + 2.0 * day), daily_ts(day), vol=vol))
    params = _mf_params(num_long_positions=3, min_avg_turnover=1_000_000.0)
    _, positions = run(MultiFactorStrategy, params, steps)
    assert "THIN" not in {s for s, q in positions.items() if q > 0}


def test_multi_factor_no_lookahead_future_days_cannot_change_past_orders():
    import random

    random.seed(3)
    names = ["A", "B", "C", "D", "E"]
    prices = dict.fromkeys(names, 400.0)
    steps: list[Bar] = []
    for day in range(95):
        for n in names:
            prices[n] *= 1 + random.uniform(-0.03, 0.035)
            steps.append(_bar(n, round(prices[n], 2), daily_ts(day), vol=2_000_000))

    per_day = len(names)
    cutoff_days = 70
    short = run(MultiFactorStrategy, _mf_params(), steps[: cutoff_days * per_day])
    long = run(MultiFactorStrategy, _mf_params(), steps)

    def norm(res, limit):
        return [
            (i, [(o.tradingsymbol, o.transaction_type, o.quantity) for o in orders])
            for i, orders in res[0]
            if i < limit
        ]

    assert norm(short, cutoff_days * per_day) == norm(long, cutoff_days * per_day)


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
# opening breakout US (paper's 5m ORB + Relative Volume, NSE)
# --------------------------------------------------------------------------

from datetime import date as _date  # noqa: E402


def _obus_params(**over):
    p = dict(OpeningBreakoutUSStrategy.presets()["balanced"])
    p.update(
        opening_range_minutes=5, rvol_lookback=14, atr_period=14, rvol_min=1.0, top_n=20,
        min_open_price=50.0, min_avg_daily_volume=400_000.0, min_atr=0.5,
        square_off_time="15:20", allow_short=True,
        sizing_method="risk_per_trade", risk_per_trade_pct=1.0, capital_allocation=2_000_000.0,
        max_position_size_pct=25.0,
    )
    p.update(over)
    return OpeningBreakoutUSStrategy.resolve_params(p)


def _weekday_days(n: int, start=_date(2026, 1, 5)):
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def _obus_day_bars(sym, day, *, or_open, or_close, or_high, or_low, or_vol,
                   post_close, post_vol=300_000.0):
    """One synthetic trading day for one symbol: a 09:15 opening 5-min bar,
    two post-OR bars (the first carries the breakout close), then a 15:20
    square-off bar. Slot order is [OR, breakout, drift, square-off]."""
    dts = datetime(day.year, day.month, day.day, 9, 15)
    hi_open = max(or_high, or_open, or_close)
    lo_open = min(or_low, or_open, or_close)
    hi_post = max(or_high, or_open, or_close, post_close) + 0.3
    lo_post = min(or_low, or_open, or_close, post_close) - 0.3
    return [
        Bar(timestamp=intraday_ts(dts, 0), open=or_open, high=hi_open, low=lo_open,
            close=or_close, volume=or_vol, instrument=sym),
        Bar(timestamp=intraday_ts(dts, 5), open=or_close, high=hi_post, low=lo_post,
            close=post_close, volume=post_vol, instrument=sym),
        Bar(timestamp=intraday_ts(dts, 10), open=post_close, high=post_close + 0.3,
            low=post_close - 0.3, close=post_close, volume=post_vol, instrument=sym),
        Bar(timestamp=intraday_ts(dts, 6 * 60 + 5), open=post_close, high=post_close + 0.3,
            low=post_close - 0.3, close=post_close, volume=50_000.0, instrument=sym),
    ]


def _obus_interleave(per_symbol_days):
    """per_symbol_days: list of {sym: [4 bars]} (one dict per day). Emit bars
    in time order (slot by slot, symbol by symbol) as a real feed would."""
    steps = []
    for day_map in per_symbol_days:
        for slot in range(4):
            for bars in day_map.values():
                steps.append(bars[slot])
    return steps


def _obus_history(syms, days, *, base=200.0, or_vol=100_000.0):
    """Quiet baseline sessions: small green opening candle, no breakout, ~1x
    RVOL. Enough of them to fill the 14-session RVOL / ATR windows."""
    per_day = []
    for i, day in enumerate(days):
        drift = base + (i % 3) - 1.0  # gentle daily variation so ATR > 0
        per_day.append({
            s: _obus_day_bars(
                s, day, or_open=drift, or_close=drift + 0.3,
                or_high=drift + 1.0, or_low=drift - 1.0, or_vol=or_vol,
                post_close=drift + 0.4,  # inside the range -> no breakout
            )
            for s in syms
        })
    return _obus_interleave(per_day)


def _obus_trade_day(specs, day):
    """specs: {sym: dict(or_open, or_close, or_vol, post_close)}. Returns the
    interleaved bar list for that single day."""
    day_map = {
        s: _obus_day_bars(s, day, or_open=k["or_open"], or_close=k["or_close"],
                          or_high=201.0, or_low=199.0, or_vol=k["or_vol"],
                          post_close=k["post_close"])
        for s, k in specs.items()
    }
    return _obus_interleave([day_map])


def test_obus_arms_top_n_by_rvol_and_trades_the_breakout():
    syms = ["AAA", "BBB", "CCC", "DDD"]
    steps = _obus_history(syms, _weekday_days(16))
    trade_day = _weekday_days(17)[-1]
    # AAA & BBB open on ~8x their usual opening volume; CCC & DDD on ~1x.
    # All four break out; only the two Stocks in Play should be armed.
    steps += _obus_trade_day({
        "AAA": {"or_open": 200.0, "or_close": 200.8, "or_vol": 800_000.0, "post_close": 203.0},
        "BBB": {"or_open": 200.0, "or_close": 200.8, "or_vol": 800_000.0, "post_close": 203.0},
        "CCC": {"or_open": 200.0, "or_close": 200.8, "or_vol": 100_000.0, "post_close": 203.0},
        "DDD": {"or_open": 200.0, "or_close": 200.8, "or_vol": 100_000.0, "post_close": 203.0},
    }, trade_day)

    emitted, positions = run(OpeningBreakoutUSStrategy, _obus_params(top_n=2), steps)
    traded = {o.tradingsymbol for _, orders in emitted for o in orders}
    assert traded == {"AAA", "BBB"}, "only the two highest-RVOL names should be armed"
    first_side: dict[str, str] = {}
    for _, orders in emitted:
        for o in orders:
            first_side.setdefault(o.tradingsymbol, o.transaction_type)
    assert first_side["AAA"] == "BUY" and first_side["BBB"] == "BUY"  # green OR -> long
    assert positions.get("AAA", 0) == 0 and positions.get("BBB", 0) == 0  # flat by 15:20


def test_obus_direction_lock_refuses_the_opposite_side_breakout():
    steps = _obus_history(["AAA", "BBB"], _weekday_days(16))
    trade_day = _weekday_days(17)[-1]
    steps += _obus_trade_day({
        # RED opening candle -> short-only -> an upside break is ignored
        "AAA": {"or_open": 200.0, "or_close": 199.2, "or_vol": 900_000.0, "post_close": 203.0},
        "BBB": {"or_open": 200.0, "or_close": 200.8, "or_vol": 900_000.0, "post_close": 203.0},
    }, trade_day)
    emitted, _ = run(OpeningBreakoutUSStrategy, _obus_params(top_n=20), steps)
    traded = {o.tradingsymbol for _, orders in emitted for o in orders}
    assert "AAA" not in traded  # red OR + upside break => no trade
    assert "BBB" in traded


def test_obus_rvol_filter_excludes_low_activity_names():
    steps = _obus_history(["AAA", "BBB"], _weekday_days(16))
    trade_day = _weekday_days(17)[-1]
    steps += _obus_trade_day({
        "AAA": {"or_open": 200.0, "or_close": 200.8, "or_vol": 100_000.0, "post_close": 203.0},
        "BBB": {"or_open": 200.0, "or_close": 200.8, "or_vol": 100_000.0, "post_close": 203.0},
    }, trade_day)
    emitted, _ = run(OpeningBreakoutUSStrategy, _obus_params(rvol_min=3.0), steps)
    assert emitted == []  # ~1x RVOL, threshold 3x => nothing armed


def test_obus_no_lookahead_future_days_cannot_change_past_orders():
    syms = ["AAA", "BBB", "CCC"]
    steps = _obus_history(syms, _weekday_days(20))
    steps += _obus_trade_day({
        "AAA": {"or_open": 200.0, "or_close": 200.8, "or_vol": 900_000.0, "post_close": 203.0},
        "BBB": {"or_open": 200.0, "or_close": 200.8, "or_vol": 110_000.0, "post_close": 203.0},
        "CCC": {"or_open": 200.0, "or_close": 200.8, "or_vol": 90_000.0, "post_close": 203.0},
    }, _weekday_days(21)[-1])

    bars_per_day = 4 * len(syms)
    cutoff = bars_per_day * 15
    short_run, _ = run(OpeningBreakoutUSStrategy, _obus_params(top_n=2), steps[:cutoff])
    long_run, _ = run(OpeningBreakoutUSStrategy, _obus_params(top_n=2), steps)
    long_truncated = [(i, o) for (i, o) in long_run if i < cutoff]

    def norm(runs):
        return [(i, [(o.tradingsymbol, o.transaction_type) for o in orders]) for i, orders in runs]

    assert norm(short_run) == norm(long_truncated)


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
# latency arbitrage (lead-lag convergence)
# --------------------------------------------------------------------------

def test_latency_arb_trades_the_laggard_toward_the_leader_then_exits():
    steps: list[Bar] = []
    lead = lag = 100.0
    for i in range(80):                       # 80 bars moving together -> high correlation
        step = 0.2 if i % 2 == 0 else -0.15
        lead += step
        lag += step
        steps.append(_bar("NIFTY", lead, daily_ts(i)))
        steps.append(_bar("NIFTYBEES", lag, daily_ts(i)))
    # leader jumps, laggard lags for a few bars
    for i in range(80, 84):
        lead += 1.2
        steps.append(_bar("NIFTY", lead, daily_ts(i)))
        steps.append(_bar("NIFTYBEES", lag, daily_ts(i)))
    # laggard catches up -> gap closes -> exit
    for i in range(84, 92):
        lag = lead
        steps.append(_bar("NIFTY", lead, daily_ts(i)))
        steps.append(_bar("NIFTYBEES", lag, daily_ts(i)))
    params = LatencyArbitrageStrategy.resolve_params({
        **LatencyArbitrageStrategy.presets()["balanced"],
        "leader_symbol": "NIFTY", "signal_lookback": 3, "divergence_bps": 20.0,
        "exit_gap_bps": 5.0, "stop_gap_bps": 5000.0, "corr_lookback": 40,
        "min_correlation": 0.5, "max_holding_bars": 0, "sizing_method": "fixed_quantity",
        "fixed_quantity": 3,
    })
    emitted, positions = run(LatencyArbitrageStrategy, params, steps)
    assert emitted, "expected a lead-lag entry"
    first = emitted[0][1][0]
    assert first.tradingsymbol == "NIFTYBEES" and first.transaction_type == "BUY"
    assert positions.get("NIFTYBEES", 0) == 0  # exited once the gap closed


def test_latency_arb_correlation_guard_blocks_uncorrelated_pair():
    import random

    random.seed(9)
    steps = []
    a = b = 100.0
    for i in range(120):
        a += random.gauss(0, 1.0)
        b += random.gauss(0, 1.0)          # independent -> low correlation
        steps.append(_bar("A", abs(a) + 50, daily_ts(i)))
        steps.append(_bar("B", abs(b) + 50, daily_ts(i)))
    params = LatencyArbitrageStrategy.resolve_params({
        **LatencyArbitrageStrategy.presets()["balanced"],
        "leader_symbol": "A", "divergence_bps": 1.0, "corr_lookback": 40,
        "min_correlation": 0.9,
    })
    emitted, _ = run(LatencyArbitrageStrategy, params, steps)
    assert emitted == []


# --------------------------------------------------------------------------
# index / futures arbitrage (cash-futures basis)
# --------------------------------------------------------------------------

def test_index_futures_arb_sells_rich_future_and_buys_spot_then_converges():
    import math

    r, q, dte = 0.065, 0.012, 30
    t = dte / 365
    spot = 24_000.0
    fair = spot * math.exp((r - q) * t)
    steps: list[Bar] = []
    # 10 aligned bars near fair value (no trade)
    for i in range(10):
        steps.append(_bar("NIFTY", spot, daily_ts(i)))
        steps.append(_bar("NIFTY-FUT", fair, daily_ts(i)))
    # future goes ~0.6% rich -> SELL future / BUY spot
    rich = fair * 1.006
    for i in range(10, 14):
        steps.append(_bar("NIFTY", spot, daily_ts(i)))
        steps.append(_bar("NIFTY-FUT", rich, daily_ts(i)))
    # converge back to fair -> unwind
    for i in range(14, 22):
        steps.append(_bar("NIFTY", spot, daily_ts(i)))
        steps.append(_bar("NIFTY-FUT", fair, daily_ts(i)))
    params = IndexFuturesArbitrageStrategy.resolve_params({
        **IndexFuturesArbitrageStrategy.presets()["balanced"],
        "spot_symbol": "NIFTY", "risk_free_rate_pct": 6.5, "dividend_yield_pct": 1.2,
        "expiry_date": "", "days_to_expiry": dte, "entry_deviation_pct": 0.3,
        "exit_deviation_pct": 0.05, "stop_deviation_pct": 5.0, "futures_lot_size": 50,
        "sizing_method": "fixed_capital", "capital_allocation": 5_000_000.0,
        "max_position_size_pct": 50.0,
    })
    emitted, positions = run(IndexFuturesArbitrageStrategy, params, steps)
    assert emitted, "expected a basis entry"
    first = {o.tradingsymbol: o.transaction_type for o in emitted[0][1]}
    assert first["NIFTY-FUT"] == "SELL" and first["NIFTY"] == "BUY"
    assert all(v % 50 == 0 for v in [o.quantity for _, os in emitted for o in os
                                     if o.tradingsymbol == "NIFTY-FUT"])
    assert positions.get("NIFTY", 0) == 0 and positions.get("NIFTY-FUT", 0) == 0


def test_index_futures_arb_flattens_before_expiry():

    steps: list[Bar] = []
    spot = 100.0
    for i in range(30):
        d = daily_ts(i)
        # keep the future rich the whole time so it would otherwise stay in a trade
        steps.append(_bar("SPOT", spot, d))
        steps.append(_bar("FUT", spot * 1.02, d))
    params = IndexFuturesArbitrageStrategy.resolve_params({
        **IndexFuturesArbitrageStrategy.presets()["balanced"],
        "spot_symbol": "SPOT", "expiry_date": "2026-01-20", "entry_deviation_pct": 0.3,
        "stop_deviation_pct": 50.0, "close_days_before_expiry": 2, "futures_lot_size": 1,
        "sizing_method": "fixed_quantity", "fixed_quantity": 10,
    })
    emitted, positions = run(IndexFuturesArbitrageStrategy, params, steps)
    # entered early, force-flat by 2026-01-18 (2 days before the 2026-01-20 expiry)
    assert emitted
    assert positions.get("SPOT", 0) == 0 and positions.get("FUT", 0) == 0


# --------------------------------------------------------------------------
# look-ahead bias + determinism
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls, params_fn, sym",
    [
        (TrendFollowingStrategy, _trend_params, "INFY"),
        (DonchianBreakoutStrategy, _donchian_params, "INFY"),
        (MeanReversionStrategy, _mr_params, "SBIN"),
        (WeaponCandleStrategy, _weapon_params, "INFY"),
        (VolatilityRegimeStrategy, _volreg_params, "INFY"),
        (RegimeAdaptiveStrategy, _regime_params, "INFY"),
    ],
    ids=["trend-following", "donchian-breakout", "mean-reversion", "weapon-candle",
         "volatility-regime", "regime-adaptive"],
)  # multi-factor look-ahead is covered separately (needs a multi-name universe)
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

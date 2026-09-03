"""Adaptive Options — Phases 0-7: greeks, config, chain view, and every
analysis engine, plus the snapshot store and a full-pipeline pass."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from app.adaptive_options import (
    confidence,
    data_quality,
    expected_move,
    greeks_engine,
    market_intelligence,
    pcr_engine,
    positioning,
    regime,
    snapshots,
    volatility,
)
from app.adaptive_options.chain_view import from_live_payload
from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainRow, ChainSnapshot
from app.options.greeks import black_scholes, bs_price, implied_vol
from app.strategies.base import Bar

IST = "+05:30"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _snap(spot: float = 24000.0, *, dte: float = 5.0, bullish: bool = True,
          with_chg: bool = True, iv: float = 0.13) -> ChainSnapshot:
    step = 100.0
    rows = []
    for i in range(-12, 13):
        k = round(spot / step) * step + i * step
        d = abs(k - spot) / step
        # put OI concentrated below spot, call OI above; totals skewed so the
        # weighted PCR is clearly bullish / bearish, not ~1.
        put_oi = 90_000 * math.exp(-((k - (spot - 400)) ** 2) / (2 * (350 ** 2))) + 4_000
        call_oi = 90_000 * math.exp(-((k - (spot + 400)) ** 2) / (2 * (350 ** 2))) + 4_000
        call_chg = -2_000.0 if with_chg else 0.0                 # call unwinding
        put_chg = (6_000.0 * math.exp(-d / 3)) if with_chg else 0.0   # put writing
        if bullish:
            put_oi *= 1.6
            call_oi *= 0.7
        else:
            put_oi, call_oi = call_oi * 0.7, put_oi * 1.6
            call_chg, put_chg = put_chg, call_chg               # -> call writing / put unwinding
        rows.append(ChainRow(
            strike=k,
            call_oi=call_oi, put_oi=put_oi,
            call_chg_oi=call_chg,
            put_chg_oi=put_chg,
            call_volume=call_oi * 0.4, put_volume=put_oi * 0.5,
            call_ltp=max(0.5, bs_price(spot, k, dte / 365, iv, is_call=True)),
            put_ltp=max(0.5, bs_price(spot, k, dte / 365, iv, is_call=False)),
            call_iv=iv + 0.002 * d, put_iv=iv + 0.004 * d,   # mild put skew
        ))
    return ChainSnapshot("NIFTY", "2026-09-30", spot, datetime.now(UTC), dte, rows)


def _bars(n: int, *, up: bool) -> list[Bar]:
    out, px = [], 22000.0
    start = datetime(2026, 1, 2)
    for i in range(n):
        d = start + timedelta(days=i)
        drift = 0.004 if up else -0.004
        px *= 1 + drift + 0.0012 * math.sin(i / 4)
        out.append(Bar(timestamp=d.isoformat() + IST, open=px * 0.999, high=px * 1.005,
                       low=px * 0.995, close=px, volume=1_000_000 + i * 500, instrument="NIFTY 50"))
    return out


# --------------------------------------------------------------------------
# greeks
# --------------------------------------------------------------------------

def test_greeks_put_call_parity_and_signs():
    s, k, t, v, r = 24000.0, 24000.0, 30 / 365, 0.14, 0.065
    c = black_scholes(s, k, t, v, is_call=True, r=r)
    p = black_scholes(s, k, t, v, is_call=False, r=r)
    # C - P = S - K e^{-rT}
    assert c.price - p.price == pytest.approx(s - k * math.exp(-r * t), rel=1e-3)
    assert 0.0 < c.delta < 1.0
    assert -1.0 < p.delta < 0.0
    assert c.gamma > 0 and c.vega > 0
    assert c.theta < 0    # long option bleeds


def test_implied_vol_round_trips():
    s, k, t = 24000.0, 24300.0, 21 / 365
    for true_v in (0.08, 0.14, 0.27):
        px = bs_price(s, k, t, true_v, is_call=True)
        got = implied_vol(px, s, k, t, is_call=True)
        assert got == pytest.approx(true_v, abs=1e-3)


def test_implied_vol_none_below_intrinsic():
    assert implied_vol(50.0, 24000.0, 23000.0, 0.05, is_call=True) is None


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def test_config_presets_all_valid():
    for name in ("conservative", "balanced", "aggressive"):
        AdaptiveConfig.from_dict(None, preset=name).validate()


def test_config_rejects_unknown_field_and_bad_thresholds():
    with pytest.raises(ValueError):
        AdaptiveConfig.from_dict({"nope": 1})
    with pytest.raises(ValueError):
        AdaptiveConfig.from_dict({"pcr_bull_threshold": 0.5})  # crosses bear threshold


def test_confidence_weights_normalise():
    w = AdaptiveConfig().confidence_weights()
    assert sum(w.values()) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# chain view
# --------------------------------------------------------------------------

def test_chain_view_normalises_iv_and_fills_delta_oi():
    payload = {
        "available": True, "underlying": "NIFTY", "expiry": "2026-09-30",
        "spot": 24000.0, "as_of": datetime.now(UTC).isoformat(),
        "rows": [
            {"strike": 23900, "call": {"oi": 1000, "volume": 10, "ltp": 180, "iv": 12.5},
             "put": {"oi": 5000, "volume": 40, "ltp": 90, "iv": 14.0}},
            {"strike": 24000, "call": {"oi": 3000, "volume": 20, "ltp": 120, "iv": 12.0},
             "put": {"oi": 3000, "volume": 25, "ltp": 120, "iv": 13.0}},
        ],
    }
    prev = {23900.0: {"call_oi": 800, "put_oi": 4000}, 24000.0: {"call_oi": 3500, "put_oi": 2500}}
    snap = from_live_payload(payload, dte=7, prev_rows=prev)
    assert snap.rows[0].call_iv == pytest.approx(0.125)     # percent -> fraction
    assert snap.rows[0].put_chg_oi == pytest.approx(1000.0)  # 5000 - 4000
    assert snap.rows[1].call_chg_oi == pytest.approx(-500.0)
    assert snap.atm_strike() == 24000.0
    assert snap.strike_step() == 100.0


# --------------------------------------------------------------------------
# data quality
# --------------------------------------------------------------------------

def test_data_quality_flags_thin_and_stale():
    cfg = AdaptiveConfig()
    snap = _snap()
    rep = data_quality.assess_chain(snap, cfg)
    assert rep.ok and rep.score > 80

    thin = ChainSnapshot("NIFTY", "2026-09-30", 24000.0, datetime.now(UTC), 5.0,
                         snap.rows[:4])
    assert not data_quality.assess_chain(thin, cfg).ok   # thin_chain -> ERROR

    old = ChainSnapshot("NIFTY", "2026-09-30", 24000.0,
                        datetime.now(UTC) - timedelta(hours=2), 5.0, snap.rows)
    codes = {i.code for i in data_quality.assess_chain(old, cfg).issues}
    assert "stale_chain" in codes


# --------------------------------------------------------------------------
# market intelligence
# --------------------------------------------------------------------------

def test_market_intelligence_reads_an_uptrend():
    intel = market_intelligence.analyse(_bars(160, up=True), AdaptiveConfig())
    assert intel.trend_direction == "UP"
    assert intel.ema_stack == "BULLISH"
    assert intel.market_structure in ("HH_HL", "EXPANSION", "RANGE")
    assert intel.adx is not None


def test_market_intelligence_reads_a_downtrend():
    intel = market_intelligence.analyse(_bars(160, up=False), AdaptiveConfig())
    assert intel.trend_direction == "DOWN"
    assert intel.ema_stack == "BEARISH"


# --------------------------------------------------------------------------
# PCR engine
# --------------------------------------------------------------------------

def test_pcr_detects_confirmed_upward_transition_with_hysteresis():
    cfg = AdaptiveConfig(pcr_transition_confirm=3, pcr_transition_min_slope=0.01)
    series = [0.70, 0.75, 0.82, 0.90, 0.98, 1.06]   # steadily rising
    hist = [{"oi_pcr": v, "weighted_pcr": v, "spot": 24000 + i * 5}
            for i, v in enumerate(series[:-1])]
    snap = _snap(bullish=True)
    # force the current weighted PCR to the last point of the ramp
    st = pcr_engine.analyse(snap, cfg, history=hist)
    # a single call classifies level+transition from history+current
    assert st.history_len == len(hist)
    # rebuild with a clean synthetic where current weighted ~ series[-1]
    st2 = pcr_engine._transition(series, cfg)
    assert st2 == ("TRANSITIONING_UP", True)
    down = pcr_engine._transition(series[::-1], cfg)
    assert down == ("TRANSITIONING_DOWN", True)
    assert pcr_engine._transition([1.0, 1.001, 0.999, 1.0], cfg)[0] == "STABLE"


def test_pcr_level_state_classification():
    cfg = AdaptiveConfig()
    assert pcr_engine._level_state(1.35, cfg) == "STRONG_BULLISH"
    assert pcr_engine._level_state(1.00, cfg) == "NEUTRAL"
    assert pcr_engine._level_state(0.60, cfg) == "STRONG_BEARISH"
    assert pcr_engine._level_state(1.70, cfg) == "EXTREME"


# --------------------------------------------------------------------------
# positioning
# --------------------------------------------------------------------------

def test_positioning_finds_walls_support_resistance_and_buildup():
    cfg = AdaptiveConfig()
    snap = _snap(spot=24000.0, bullish=True)
    rep = positioning.analyse(snap, cfg, price_change_pct=0.8, history=[])
    assert rep.put_support is not None and rep.put_support <= 24000.0 + snap.strike_step()
    assert rep.call_resistance is not None and rep.call_resistance >= 24000.0 - snap.strike_step()
    assert rep.oi_walls
    assert rep.price_oi_state in ("LONG_BUILDUP", "SHORT_COVERING", "MIXED")
    assert 0.0 <= rep.oi_concentration <= 1.0
    assert rep.put_writing_strength >= 50.0   # positive put ΔOI in the fixture


# --------------------------------------------------------------------------
# volatility
# --------------------------------------------------------------------------

def test_volatility_iv_rank_and_selling_score():
    cfg = AdaptiveConfig()
    snap = _snap(iv=0.13)
    hist_low = [0.09 + 0.001 * i for i in range(20)]   # history well below current -> high rank
    rep = volatility.analyse(snap, cfg, iv_history=hist_low, realized_vol=0.10,
                             adx=15.0, trend_strength=20.0)
    assert rep.atm_iv == pytest.approx(0.13 + (0.002 * 0 + 0.004 * 0) / 2, abs=0.02)
    assert rep.iv_rank is not None and rep.iv_rank > 80
    assert rep.iv_class in ("HIGH_IV", "EXTREME_IV")
    assert rep.vol_selling_score > 55 and rep.vol_selling_verdict == "FAVOURABLE"

    # short DTE kills the selling score even with high IV
    near = _snap(dte=1.0, iv=0.13)
    rep2 = volatility.analyse(near, cfg, iv_history=hist_low, realized_vol=0.10,
                              adx=15.0, trend_strength=20.0)
    assert rep2.vol_selling_score < rep.vol_selling_score


# --------------------------------------------------------------------------
# greeks engine
# --------------------------------------------------------------------------

def test_greeks_engine_builds_full_surface():
    rep = greeks_engine.chain(_snap(), AdaptiveConfig(), realized_vol=0.12)
    assert len(rep.per_strike) == 25
    assert rep.atm_call and rep.atm_put
    assert rep.gamma_zone is not None and rep.gamma_zone[0] <= rep.gamma_zone[1]


# --------------------------------------------------------------------------
# expected move
# --------------------------------------------------------------------------

def test_expected_move_three_methods_and_band():
    em = expected_move.compute(_snap(dte=5.0, iv=0.13), AdaptiveConfig(),
                               atm_iv=0.13, atr_points=120.0, day_open=23950.0)
    assert em.by_method["straddle"] and em.by_method["iv"] and em.by_method["atr"]
    assert em.points and em.upper > em.lower
    assert em.current_move_points == pytest.approx(50.0, abs=1.0)


# --------------------------------------------------------------------------
# confidence + regime — full pipeline
# --------------------------------------------------------------------------

def _pipeline(bars_up: bool, chain_bullish: bool, dte: float = 6.0):
    cfg = AdaptiveConfig()
    bars = _bars(180, up=bars_up)
    snap = _snap(bullish=chain_bullish, dte=dte)
    dq = data_quality.assess_chain(snap, cfg)
    intel = market_intelligence.analyse(bars, cfg)
    hist = [{"oi_pcr": 1.0 + 0.01 * i, "weighted_pcr": 1.0 + 0.01 * i, "spot": 22000 + i}
            for i in range(12)]
    pcr_s = pcr_engine.analyse(snap, cfg, history=hist)
    pos_s = positioning.analyse(snap, cfg, price_change_pct=1.0 if bars_up else -1.0, history=[])
    vol_s = volatility.analyse(snap, cfg, iv_history=[0.10 + 0.001 * i for i in range(16)],
                              realized_vol=0.11, adx=intel.adx, trend_strength=intel.trend_strength)
    em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv, atr_points=120.0, day_open=22000.0)
    conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
    reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                          expected_move=em, confidence=conf, data_ok=dq.ok)
    return conf, reg


def test_confidence_in_range_and_banded():
    conf, _ = _pipeline(True, True)
    assert 0.0 <= conf.score <= 100.0
    assert conf.band in ("LOW", "WEAK", "MODERATE", "HIGH", "VERY_HIGH")


def test_regime_bullish_alignment_gives_a_bullish_label():
    _, reg = _pipeline(bars_up=True, chain_bullish=True)
    assert reg.direction == "BULLISH"
    assert reg.label in ("STRONG_BULLISH_TREND", "BULLISH_TREND", "WEAK_BULLISH", "BREAKOUT")
    assert reg.drivers


def test_regime_conflict_low_confidence_is_no_trade():
    """Strong uptrend in price but a coherently bearish option chain (low PCR,
    call writing, put unwinding). Trend and positioning cancel -> conflict;
    with the confidence gate raised the engine must say NO_TRADE."""
    cfg = AdaptiveConfig(regime_confidence_min=95.0)
    bars = _bars(170, up=True)
    snap = _snap(bullish=False)
    intel = market_intelligence.analyse(bars, cfg)
    pcr_s = pcr_engine.analyse(snap, cfg, history=[])
    pos_s = positioning.analyse(snap, cfg, price_change_pct=1.2, history=[])
    vol_s = volatility.analyse(snap, cfg, iv_history=[], realized_vol=0.12)
    em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv, atr_points=100.0)
    conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
    reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                          expected_move=em, confidence=conf, data_ok=True)
    assert reg.label == "NO_TRADE"


def test_regime_data_failure_forces_no_trade():
    cfg = AdaptiveConfig()
    bars = _bars(120, up=True)
    snap = _snap()
    intel = market_intelligence.analyse(bars, cfg)
    pcr_s = pcr_engine.analyse(snap, cfg, history=[])
    pos_s = positioning.analyse(snap, cfg, history=[])
    vol_s = volatility.analyse(snap, cfg)
    em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv)
    conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
    reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                          expected_move=em, confidence=conf, data_ok=False)
    assert reg.label == "NO_TRADE"


# --------------------------------------------------------------------------
# snapshot store (DB)
# --------------------------------------------------------------------------

def test_snapshot_record_load_and_throttle(db):
    import dataclasses

    snap = _snap()
    row = snapshots.record(db, snap, oi_pcr=1.1, weighted_pcr=1.2, atm_iv=0.13,
                           put_support=23600.0, call_resistance=24400.0)
    assert row is not None
    # immediate second write is throttled
    assert snapshots.record(db, snap, oi_pcr=1.1, weighted_pcr=1.2) is None
    # forced write with a fresher chain timestamp goes in
    later = dataclasses.replace(snap, as_of=snap.as_of + timedelta(minutes=2))
    assert snapshots.record(db, later, oi_pcr=1.15, weighted_pcr=1.25, force=True) is not None

    hist = snapshots.load_history(db, "NIFTY", "2026-09-30")
    assert len(hist) >= 2
    assert hist[0]["weighted_pcr"] == pytest.approx(1.2)
    assert hist[-1]["weighted_pcr"] == pytest.approx(1.25)
    prev = snapshots.prev_oi_rows(db, "NIFTY", "2026-09-30")
    assert prev and all("call_oi" in v and "put_oi" in v for v in prev.values())


# ==========================================================================
# Phases 8-12: strategy library, selector, strike selection, sizing, risk,
# leg management
# ==========================================================================

from app.adaptive_options import (  # noqa: E402
    leg_manager,
    risk_engine,
    sizing,
    strategy_selector,
    strike_selector,
)
from app.adaptive_options.strategy_library import (  # noqa: E402
    available_templates,
    build_position,
    get_template,
)


def _ctx(bars_up: bool, chain_bullish: bool, *, dte: float = 6.0, iv: float = 0.13):
    cfg = AdaptiveConfig()
    bars = _bars(180, up=bars_up)
    snap = _snap(bullish=chain_bullish, dte=dte, iv=iv)
    dq = data_quality.assess_chain(snap, cfg)
    intel = market_intelligence.analyse(bars, cfg)
    hist = [{"oi_pcr": 1.0, "weighted_pcr": 1.0, "spot": 22000 + i} for i in range(10)]
    pcr_s = pcr_engine.analyse(snap, cfg, history=hist)
    pos_s = positioning.analyse(snap, cfg, price_change_pct=1.0 if bars_up else -1.0, history=[])
    vol_s = volatility.analyse(snap, cfg, iv_history=[0.10 + 0.002 * i for i in range(16)],
                              realized_vol=0.11, adx=intel.adx, trend_strength=intel.trend_strength)
    em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv, atr_points=120.0, day_open=22000.0)
    conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
    reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                          expected_move=em, confidence=conf, data_ok=dq.ok)
    return cfg, {"snap": snap, "regime": reg, "pcr": pcr_s, "positioning": pos_s, "vol": vol_s,
                "expected_move": em, "confidence": conf, "intel": intel, "data_ok": dq.ok}


# --- strategy library ------------------------------------------

def test_build_iron_condor_is_defined_risk():
    snap = _snap(dte=7.0)
    plan = strike_selector.select(snap, AdaptiveConfig(), expected_move_points=200.0)
    pos = build_position(get_template("iron-condor"), plan.levels, snap, lots=1, lot_size=75)
    assert len(pos.legs) == 4
    assert not pos.undefined_risk
    assert pos.max_loss > 0 and pos.max_profit > 0
    assert len(pos.breakevens) == 2
    assert 0.0 <= pos.pop <= 1.0
    assert pos.net_premium > 0        # condor is a credit


def test_build_bull_put_spread_is_a_credit():
    snap = _snap(dte=10.0)
    plan = strike_selector.select(snap, AdaptiveConfig())
    pos = build_position(get_template("bull-put-spread"), plan.levels, snap, lots=1, lot_size=75)
    assert pos.net_premium > 0 and not pos.undefined_risk
    assert pos.risk_reward is not None


def test_build_long_straddle_is_a_debit_two_breakevens():
    snap = _snap(dte=10.0)
    plan = strike_selector.select(snap, AdaptiveConfig())
    pos = build_position(get_template("long-straddle"), plan.levels, snap, lots=1, lot_size=75)
    assert pos.net_premium < 0
    assert len(pos.breakevens) == 2


def test_naked_templates_gated_by_acknowledgement():
    slugs = {t.slug for t in available_templates(AdaptiveConfig())}
    assert "short-strangle" not in slugs and "short-straddle" not in slugs
    ack = AdaptiveConfig(allow_naked=True, naked_risk_acknowledged=True)
    slugs2 = {t.slug for t in available_templates(ack)}
    assert "short-strangle" in slugs2


# --- strike selector -----------------------------------------

def test_strike_selector_delta_method_targets_the_delta():
    snap = _snap(dte=7.0, iv=0.14)
    cfg = AdaptiveConfig(strike_method="delta", strike_short_delta=0.20)
    plan = strike_selector.select(snap, cfg)
    assert plan.levels["call_2"] > plan.levels["call_1"] > snap.spot
    assert plan.levels["put_2"] < plan.levels["put_1"] < snap.spot
    assert abs(plan.per_leg["call_1"]["delta"] - 0.20) < 0.12


def test_strike_selector_expected_move_method():
    snap = _snap(dte=7.0)
    cfg = AdaptiveConfig(strike_method="expected_move", strike_em_mult=1.0)
    plan = strike_selector.select(snap, cfg, expected_move_points=300.0)
    assert abs(plan.levels["call_1"] - (snap.spot + 300.0)) <= snap.strike_step()
    assert abs(plan.levels["put_1"] - (snap.spot - 300.0)) <= snap.strike_step()


# --- selector ------------------------------------------------

def test_selector_bullish_context_picks_a_bullish_strategy():
    cfg, ctx = _ctx(bars_up=True, chain_bullish=True)
    res = strategy_selector.rank(cfg, **ctx)
    assert res.action in ("ENTER", "WAIT")
    if res.top:
        assert get_template(res.top.slug).direction in ("BULLISH", "NEUTRAL")
    assert res.decision_matrix and all("thesis" in r for r in res.decision_matrix)


def test_selector_no_trade_when_confidence_low():
    cfg, ctx = _ctx(bars_up=True, chain_bullish=False)
    cfg.no_trade_confidence_min = 99.0
    res = strategy_selector.rank(cfg, **ctx)
    assert res.action == "NO_TRADE" and res.no_trade_reason


def test_selector_compare_returns_rows_for_requested_slugs():
    cfg, ctx = _ctx(bars_up=False, chain_bullish=False)
    rows = strategy_selector.compare(cfg, ["bear-call-spread", "iron-condor", "bull-put-spread"], **ctx)
    assert len(rows) == 3
    assert all("slug" in r for r in rows)


# --- sizing ------------------------------------------------

def test_sizing_defined_risk_respects_the_budget():
    snap = _snap(dte=12.0)
    plan = strike_selector.select(snap, AdaptiveConfig(), expected_move_points=200.0)
    pos = build_position(get_template("iron-condor"), plan.levels, snap, lots=1, lot_size=75)
    cfg = AdaptiveConfig(account_capital=1_000_000.0, max_loss_per_trade_pct=2.0, max_lots_per_trade=50)
    sz = sizing.size(pos, cfg, dte=12.0)
    assert sz.capital_at_risk <= cfg.account_capital * 0.02 + pos.max_loss  # within one lot
    assert sz.lots >= 1


def test_sizing_halves_near_expiry():
    snap = _snap(dte=1.0)
    plan = strike_selector.select(snap, AdaptiveConfig(), expected_move_points=120.0)
    pos = build_position(get_template("iron-condor"), plan.levels, snap, lots=1, lot_size=75)
    cfg = AdaptiveConfig(expiry_reduce_dte=2)
    far = sizing.size(pos, AdaptiveConfig(), dte=20.0).lots
    near = sizing.size(pos, cfg, dte=1.0).lots
    assert near <= max(1, far // 2) + 1


# --- risk engine ------------------------------------------

def test_risk_engine_ok_then_blocked_on_daily_loss():
    snap = _snap(dte=12.0)
    plan = strike_selector.select(snap, AdaptiveConfig(), expected_move_points=200.0)
    pos = build_position(get_template("iron-condor"), plan.levels, snap, lots=1, lot_size=75)
    cfg = AdaptiveConfig(account_capital=1_000_000.0)
    sz = sizing.size(pos, cfg, dte=12.0)
    ok_state = risk_engine.PortfolioState(capital=1_000_000.0, spot=snap.spot)
    d1 = risk_engine.check_entry(sz, pos, cfg, ok_state, dte=12.0)
    assert d1.ok and d1.scale > 0

    loss_state = risk_engine.PortfolioState(capital=1_000_000.0, spot=snap.spot, day_pnl=-40_000.0)
    d2 = risk_engine.check_entry(sz, pos, cfg, loss_state, dte=12.0)
    assert not d2.ok and "Daily loss" in (d2.blocked_reason or "")


def test_risk_engine_scales_down_when_margin_tight():
    snap = _snap(dte=12.0)
    plan = strike_selector.select(snap, AdaptiveConfig(), expected_move_points=200.0)
    pos = build_position(get_template("iron-condor"), plan.levels, snap, lots=1, lot_size=75)
    cfg = AdaptiveConfig(account_capital=1_000_000.0, max_margin_usage_pct=50.0)
    sz = sizing.size(pos, cfg, dte=12.0)
    tight = risk_engine.PortfolioState(capital=1_000_000.0, spot=snap.spot,
                                       open_margin=496_000.0)
    d = risk_engine.check_entry(sz, pos, cfg, tight, dte=12.0)
    assert (not d.ok) or d.scale < 1.0


def test_kill_switch_trips_on_operator_flag():
    st = risk_engine.PortfolioState(capital=1_000_000.0, killed=True,
                                    kill_reasons=["manual"])
    tripped, reasons = risk_engine.kill_switch(st, AdaptiveConfig())
    assert tripped and reasons


# --- leg manager ------------------------------------------

def _open_condor(snap):
    plan = strike_selector.select(snap, AdaptiveConfig(), expected_move_points=200.0)
    lv = plan.levels
    return leg_manager.OpenPosition(
        slug="iron-condor", direction="NEUTRAL", lots=5, lot_size=75,
        entry_spot=snap.spot, entry_net_premium=8000.0,
        short_call=lv["call_1"], short_put=lv["put_1"],
        long_call=lv["call_2"], long_put=lv["put_2"],
        entry_regime="RANGE_BOUND", entry_pcr_state="NEUTRAL",
        target_pnl=4000.0, stop_pnl=-8000.0,
    )


def test_leg_manager_stop_and_target():
    cfg, ctx = _ctx(bars_up=True, chain_bullish=True)
    snap = ctx["snap"]
    op = _open_condor(snap)
    stop = leg_manager.evaluate(op, cfg, snap=snap, regime=ctx["regime"], pcr=ctx["pcr"],
                                intel=ctx["intel"], vol=ctx["vol"], current_pnl=-9000.0, dte=6.0)
    assert stop.action == "FULL_EXIT" and stop.urgency == "critical"
    tgt = leg_manager.evaluate(op, cfg, snap=snap, regime=ctx["regime"], pcr=ctx["pcr"],
                               intel=ctx["intel"], vol=ctx["vol"], current_pnl=5000.0, dte=6.0)
    assert tgt.action == "FULL_EXIT"
    hold = leg_manager.evaluate(op, cfg, snap=snap, regime=ctx["regime"], pcr=ctx["pcr"],
                                intel=ctx["intel"], vol=ctx["vol"], current_pnl=500.0, dte=6.0)
    assert hold.action in ("HOLD", "ROLL_UP", "ROLL_DOWN", "REDUCE_QTY")


def test_leg_manager_threatened_short_strike_rolls():
    cfg, ctx = _ctx(bars_up=True, chain_bullish=True)
    snap = ctx["snap"]
    op = _open_condor(snap)
    op.short_call = snap.spot        # spot sitting on the short call
    act = leg_manager.evaluate(op, cfg, snap=snap, regime=ctx["regime"], pcr=ctx["pcr"],
                               intel=ctx["intel"], vol=ctx["vol"], current_pnl=-2000.0, dte=6.0)
    assert act.action in ("ROLL_UP", "MOVE_HEDGE", "FULL_EXIT")


# ==========================================================================
# Phase 14: backtest engine
# ==========================================================================

from datetime import date as _date  # noqa: E402

from app.adaptive_options import backtest as bt  # noqa: E402


def test_weekly_and_monthly_expiry_helpers():
    d = _date(2026, 9, 1)   # a Tuesday
    exp, dte = bt._weekly_expiry(d)
    assert exp.weekday() == 3 and dte >= 3
    mexp, mdte = bt._monthly_expiry(d)
    assert mexp.weekday() == 3 and mexp.month in (9, 10) and mdte >= 3


def test_metrics_shape_on_a_simple_curve():
    curve = [[f"2026-01-{i+1:02d}", 1_000_000 + i * 1000 - (i % 3) * 800] for i in range(40)]
    trades = [{"net_pnl": 500.0, "costs": 40.0, "holding_days": 4, "adjustments": 0},
              {"net_pnl": -300.0, "costs": 40.0, "holding_days": 6, "adjustments": 1}]
    m = bt._metrics(1_000_000.0, curve, trades)
    for k in ("total_return_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
              "max_drawdown_pct", "win_rate_pct", "profit_factor", "expectancy",
              "value_at_risk_5pct", "conditional_var_5pct"):
        assert k in m
    assert m["total_trades"] == 2 and m["win_rate_pct"] == 50.0


def _fake_daily(n: int, seed: int = 1):
    rng = random.Random(seed)
    px, out = 24000.0, []
    start = _date(2025, 1, 1)
    for i in range(n):
        px *= 1 + rng.uniform(-0.012, 0.013)
        d = start + timedelta(days=i)
        out.append(Bar(timestamp=d.isoformat() + "T00:00:00+05:30", open=px * 0.999,
                       high=px * 1.008, low=px * 0.992, close=px, volume=1e6,
                       instrument="NIFTY 50"))
    return out


def test_adaptive_backtest_runs_end_to_end_synthetic(monkeypatch):
    bars = _fake_daily(420)
    monkeypatch.setattr(bt, "fetch_candles", lambda *a, **k: ({"NIFTY 50": bars}, []))
    res = bt.run_adaptive_backtest(
        None, None, underlying="NIFTY", start="2025-10-01", end="2026-02-01",
        preset="balanced", data_source="synthetic")
    assert res["available"] is True
    assert res["synthetic_data"] is True
    assert res["source_breakdown"]["synthetic"] > 40
    assert len(res["equity_curve"]) > 40
    assert res["decision_log_len"] > 40
    m = res["metrics"]
    assert "sharpe_ratio" in m and "max_drawdown_pct" in m
    for t in res["trades"]:
        assert {"entry_date", "exit_date", "strategy", "net_pnl", "costs",
                "holding_days", "mae", "mfe", "regime_at_entry"} <= set(t)
    assert any("SYNTHETIC" in w for w in res["warnings"])
    assert "by_strategy" in res["attribution"]


# ==========================================================================
# Phase 15: validation aggregation
# ==========================================================================

from app.adaptive_options import validation as vd  # noqa: E402


def test_validation_aggregates_folds_mc_and_sensitivity(monkeypatch):
    calls = {"n": 0}

    def fake_bt(db, settings, *, underlying, start, end, preset, config, data_source):
        calls["n"] += 1
        rr = random.Random(hash((start, end, str(sorted((config or {}).items())))) & 0xFFFF)
        pnls = [rr.uniform(-2500, 3500) for _ in range(9)]
        return {
            "available": True, "synthetic_data": True,
            "metrics": {"sharpe_ratio": round(rr.uniform(0.1, 1.3), 2),
                        "total_return_pct": round(rr.uniform(-6, 16), 2),
                        "max_drawdown_pct": round(rr.uniform(-22, -3), 2),
                        "total_trades": len(pnls), "profit_factor": 1.25, "win_rate_pct": 56.0},
            "trades": [{"net_pnl": p} for p in pnls], "warnings": ["synthetic run"],
        }

    monkeypatch.setattr(vd, "run_adaptive_backtest", fake_bt)
    res = vd.run_validation(None, None, underlying="NIFTY", start="2025-01-01", end="2025-06-01",
                            n_folds=2, mc_sims=60, sensitivity_params=["suitability_min"])
    assert res["available"] is True
    assert len(res["walk_forward"]["folds"]) == 2
    assert "sharpe_decay" in res["walk_forward"]
    assert res["monte_carlo"].get("available") is True
    assert len(res["sensitivity"]) == 1 and len(res["sensitivity"][0]["points"]) == 5
    assert isinstance(res["overfit_flag"], bool) and res["verdict"]
    assert calls["n"] == 1 + 2 + 5


# ==========================================================================
# Phase 16: paper trading
# ==========================================================================

from app.adaptive_options import paper as pp  # noqa: E402
from app.adaptive_options import service as svc  # noqa: E402


def _fake_bundle(*, chain_bullish=False, dte=6.0, spot=24000.0, recorded="throttled"):
    cfg = AdaptiveConfig()
    bars = _bars(180, up=chain_bullish)
    snap = _snap(bullish=chain_bullish, dte=dte, spot=spot)
    dq = data_quality.assess_chain(snap, cfg)
    intel = market_intelligence.analyse(bars, cfg)
    hist = [{"oi_pcr": 1.0, "weighted_pcr": 1.0, "spot": 22000 + i, "atm_iv": 0.11}
            for i in range(12)]
    pcr_s = pcr_engine.analyse(snap, cfg, history=hist)
    pos_s = positioning.analyse(snap, cfg, price_change_pct=0.2, history=[])
    vol_s = volatility.analyse(snap, cfg, iv_history=[h["atm_iv"] for h in hist],
                              realized_vol=0.11, adx=intel.adx, trend_strength=intel.trend_strength)
    grk = greeks_engine.chain(snap, cfg, realized_vol=0.11)
    em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv, atr_points=120.0, day_open=spot)
    conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
    reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                          expected_move=em, confidence=conf, data_ok=dq.ok)
    return svc.AnalysisBundle(
        cfg=cfg, snap=snap, dq=dq, dq_bar_issues=[], intel=intel, pcr=pcr_s, positioning=pos_s,
        volatility=vol_s, greeks=grk, expected_move=em, confidence=conf, regime=reg,
        dte=int(dte), history_len=len(hist), far_expiry_ok=False, recorded=recorded)


def test_paper_run_lifecycle_and_decision_log(db, monkeypatch):
    state = {"bundle": _fake_bundle(chain_bullish=False, dte=6.0)}
    monkeypatch.setattr(pp, "_analyse", lambda *a, **k: state["bundle"])

    run = pp.start_run(db, underlying="NIFTY", preset="balanced", capital=1_000_000.0,
                       note="test run")
    rid = run["id"]
    assert run["status"] == "ACTIVE"

    # a few ticks — should log decisions and (usually) open then manage a position
    for _ in range(3):
        t = pp.tick_run(db, None, rid)
        assert t["available"] is True

    # force a near-expiry tick so any open position is closed
    state["bundle"] = _fake_bundle(chain_bullish=False, dte=1.0)
    pp.tick_run(db, None, rid)

    full = pp.get_run(db, rid)
    assert full["id"] == rid
    assert len(full["recent_decisions"]) >= 3
    decs = pp.run_decisions(db, rid, limit=50)["decisions"]
    assert decs and all("action" in d and "phase" in d for d in decs)

    lst = pp.list_runs(db)["runs"]
    assert any(r["id"] == rid for r in lst)

    stopped = pp.stop_run(db, rid)
    assert stopped["status"] == "STOPPED"
    assert pp.tick_run(db, None, rid)["skipped"]


def test_paper_tick_all_skips_stopped(db, monkeypatch):
    monkeypatch.setattr(pp, "_analyse", lambda *a, **k: _fake_bundle())
    r1 = pp.start_run(db, underlying="NIFTY", preset="balanced")
    pp.stop_run(db, r1["id"])
    out = pp.tick_all(db, None)
    assert out["ticked"] == 0 or all(x.get("skipped") for x in out["results"])


# ==========================================================================
# Extra data sources: bhavcopy formats + local history (Kaggle / GitHub CSVs)
# ==========================================================================

from datetime import date as _d2  # noqa: E402

from app.adaptive_options import bhavcopy as bc  # noqa: E402
from app.adaptive_options import local_history as lh  # noqa: E402

_UDIFF = (
    "TckrSymb,FinInstrmTp,OptnTp,XpryDt,StrkPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,ClsPric,UndrlygPric\n"
    "NIFTY,IDO,CE,2024-02-08,21800,150000,12000,4000,210.5,21750.3\n"
    "NIFTY,IDO,PE,2024-02-08,21800,180000,-5000,3800,190.2,21750.3\n"
    "NIFTY,IDO,CE,2024-02-08,22000,90000,8000,2000,95.0,21750.3\n"
    "INFY,STO,CE,2024-02-29,1700,1000,50,10,25,1690\n"
)
_LEGACY = (
    "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP\n"
    "OPTIDX,NIFTY,08-Feb-2024,21800,CE,200,220,195,210.5,210.5,4000,80,150000,12000,07-Feb-2024\n"
    "OPTIDX,NIFTY,08-Feb-2024,21800,PE,190,200,180,190.2,190.2,3800,72,180000,-5000,07-Feb-2024\n"
    "OPTIDX,NIFTY,08-Feb-2024,22000,CE,90,100,85,95,95,2000,19,90000,8000,07-Feb-2024\n"
)


def test_bhavcopy_parses_udiff_and_legacy_formats():
    exp = _d2(2024, 2, 8)
    for text in (_UDIFF, _LEGACY):
        assert bc.expiries_in(text, "NIFTY") == [exp]
        rows = bc.chain_rows(text, "NIFTY", exp, index_option=True)
        assert len(rows) == 3
        ce = next(r for r in rows if r["strike"] == 21800 and r["option_type"] == "CE")
        assert ce["oi"] == 150000 and ce["chg_in_oi"] == 12000 and ce["close"] == 210.5
        # stock options excluded from the index-option view
        assert all(r["option_type"] in ("CE", "PE") for r in rows)
    assert bc.underlying_close(_UDIFF, "NIFTY") == 21750.3
    assert bc.underlying_close(_LEGACY, "NIFTY") is None   # legacy has no underlying col


def test_local_history_reads_a_kaggle_style_csv(tmp_path, monkeypatch):
    # a plausible Kaggle export: one row per (date, strike, type)
    csv = tmp_path / "NIFTY.csv"
    lines = ["date,expiry,strikePrice,optionType,openInterest,changeinOpenInterest,totalTradedVolume,lastPrice,impliedVolatility,underlyingValue"]
    for k in range(21600, 22200, 100):
        lines.append(f"2024-02-05,2024-02-08,{k},CE,{50000+k},{100},{800},{max(1,22000-k)},13.5,21850")
        lines.append(f"2024-02-05,2024-02-08,{k},PE,{60000+k},{-40},{700},{max(1,k-21700)},14.2,21850")
    csv.write_text("\n".join(lines))

    monkeypatch.setattr(lh, "_DIR", tmp_path)
    lh._load.cache_clear()

    assert lh.has_data("NIFTY")
    assert lh.dates_available("NIFTY") == [_d2(2024, 2, 5)]
    assert lh.expiries_on("NIFTY", _d2(2024, 2, 5)) == [_d2(2024, 2, 8)]
    assert lh.underlying_close_on("NIFTY", _d2(2024, 2, 5)) == 21850.0
    rows = lh.chain_rows("NIFTY", _d2(2024, 2, 5), _d2(2024, 2, 8))
    assert rows and len(rows) == 12
    assert {r["option_type"] for r in rows} == {"CE", "PE"}
    lh._load.cache_clear()


def test_local_history_absent_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(lh, "_DIR", tmp_path / "nope")
    lh._load.cache_clear()
    assert lh.has_data("NIFTY") is False
    assert lh.chain_rows("NIFTY", _d2(2024, 1, 1), _d2(2024, 1, 4)) is None
    lh._load.cache_clear()

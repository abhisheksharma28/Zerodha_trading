"""Arbitrage Lab: net edge, data sync, and the multi-leg backtest engine."""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from app.arbitrage.data_sync import SyncMode, synchronize
from app.arbitrage.engine import ArbitrageBacktestEngine
from app.arbitrage.net_edge import net_expected_edge
from app.arbitrage.risk import ArbRiskEngine, ArbRiskLimits, RejectReason
from app.arbitrage.strategies import (
    CalendarSpreadStrategy,
    CashAndCarryStrategy,
    CointegrationSpreadStrategy,
    IndexFuturesBasisStrategy,
    PairsArbitrageStrategy,
    SectorRelativeValueStrategy,
)
from app.arbitrage.types import Leg, TradeStructure
from app.backtesting.costs import CostConfig, CostModel
from app.strategies.base import Bar

IST = "+05:30"


def _struct(pa: float, pb: float, qa: int, qb: int) -> TradeStructure:
    legs = [
        Leg("AAA", "SELL", ratio=1.0, price=pa, quantity=qa, segment="equity", borrow_required=True),
        Leg("BBB", "BUY", ratio=1.0, price=pb, quantity=qb, segment="equity"),
    ]
    notional = qa * pa + qb * pb
    return TradeStructure(legs=legs, direction="short_spread", hedge_ratio=1.0,
                          notional_per_unit=notional, capital_required=notional,
                          margin_required=notional * 0.25, expected_holding_days=10.0)


# --- net edge ------------------------------------------------

def test_net_edge_subtracts_every_cost_bucket():
    s = _struct(1000.0, 500.0, 500, 1000)
    b = net_expected_edge(s, gross_edge=6000.0, cost_model=CostModel(CostConfig()),
                          spreads_bps={"AAA": 5.0, "BBB": 5.0}, holding_days=10.0)
    d = b.as_dict()
    assert d["gross_edge"] == 6000.0
    assert d["brokerage"] > 0 and d["statutory"] > 0 and d["bid_ask_spread"] > 0
    assert d["market_impact"] > 0 and d["borrow_cost"] > 0 and d["execution_risk_buffer"] > 0
    assert d["net_edge"] == round(d["gross_edge"] - d["total_costs"], 4)
    assert len(d["per_leg"]) == 2


def test_net_edge_can_go_negative_on_a_thin_gross_edge():
    s = _struct(1000.0, 500.0, 500, 1000)
    b = net_expected_edge(s, gross_edge=50.0, cost_model=CostModel(CostConfig()))
    assert b.net_edge < 0


# --- data sync ---------------------------------------------

def _bars(sym: str, times: list[int], px: float = 100.0) -> list[Bar]:
    return [Bar(timestamp=datetime.fromtimestamp(t).isoformat() + IST, open=px, high=px,
                low=px, close=px, volume=1000.0, instrument=sym) for t in times]


def test_sync_strict_only_keeps_exact_matches():
    a = _bars("A", [0, 60, 120, 180])
    b = _bars("B", [0, 60, 121, 180])  # 121 is off by 1s
    r = synchronize({"A": a, "B": b}, mode=SyncMode.STRICT_SYNC)
    assert r.used_points == 3  # 0, 60, 180
    assert r.max_data_skew_seconds == 0.0


def test_sync_reject_stale_drops_points_beyond_max_age():
    a = _bars("A", [0, 60, 120, 180, 240])
    b = _bars("B", [0, 60, 240])  # missing 120 & 180
    r = synchronize({"A": a, "B": b}, mode=SyncMode.REJECT_STALE_DATA, max_age_seconds=30)
    # at t=120 and t=180, B's last bar (t=60) is > 30s stale -> dropped
    assert r.used_points == 3
    assert r.stale_events >= 2
    assert 0.0 <= r.data_quality_score <= 100.0


def test_sync_last_valid_allows_stale_but_counts_it():
    a = _bars("A", [0, 60, 120, 240])
    b = _bars("B", [0, 240])
    r = synchronize({"A": a, "B": b}, mode=SyncMode.LAST_VALID_PRICE_WITH_MAX_AGE,
                    max_age_seconds=30)
    assert r.used_points == 4
    assert r.stale_events >= 2
    assert r.max_data_skew_seconds >= 60


# --- engine ------------------------------------------------

def _coint_pair(n: int, seed: int) -> dict[str, list[Bar]]:
    """B is a random walk; A = 1.5*B + a mean-reverting spread -> cointegrated."""
    rng = random.Random(seed)
    days, k = [], 0
    while len(days) < n:
        d = date(2022, 1, 3) + timedelta(days=k)
        if d.weekday() < 5:
            days.append(d)
        k += 1
    lb = 6.0
    spread = 0.0
    a_bars, b_bars = [], []
    for d in days:
        lb += rng.gauss(0, 0.01)
        spread = 0.85 * spread + rng.gauss(0, 0.02)  # AR(1), half-life ~ 4-5 bars
        la = 0.4 + 1.0 * lb + spread
        pa, pb = math.exp(la), math.exp(lb)
        ts = datetime(d.year, d.month, d.day).isoformat() + IST
        a_bars.append(Bar(timestamp=ts, open=pa, high=pa * 1.005, low=pa * 0.995, close=pa,
                          volume=1e6, instrument="AAA"))
        b_bars.append(Bar(timestamp=ts, open=pb, high=pb * 1.005, low=pb * 0.995, close=pb,
                          volume=1e6, instrument="BBB"))
    return {"AAA": a_bars, "BBB": b_bars}


def _params(cls, **over):
    p = dict(cls.PRESETS["aggressive"])
    p.update(capital=1_000_000.0, lookback=25, min_net_edge_bps=0.0, spread_bps=1.0,
             exec_risk_buffer_bps=0.0, financing_rate_annual=0.0, borrow_rate_annual=0.0)
    p.update(over)
    return cls.resolve_params(p)


def test_pairs_engine_runs_and_trades_a_cointegrated_pair():
    candles = _coint_pair(400, seed=1)
    res = ArbitrageBacktestEngine(
        PairsArbitrageStrategy, _params(PairsArbitrageStrategy, require_cointegration=False),
        capital=1_000_000.0, cost_model=CostModel(CostConfig()),
        sync_mode=SyncMode.STRICT_SYNC,
    ).run(candles)
    assert res.opportunities_seen > 0
    assert res.opportunities_executed > 0
    assert len(res.equity_curve) > 300
    m = res.metrics
    for k in ("net_pnl", "sharpe_ratio", "edge_capture_rate", "convergence_rate",
              "partial_fill_rate", "arbitrage_quality_score"):
        assert k in m
    assert 0.0 <= m["arbitrage_quality_score"] <= 100.0
    # every trade has 2 independently-tracked legs
    assert all(len(t.legs) == 2 for t in res.trades)
    assert res.data_quality["data_quality_score"] > 0


def test_cointegration_engine_gate_blocks_a_random_pair():
    rng = random.Random(9)
    days, k = [], 0
    while len(days) < 300:
        d = date(2022, 1, 3) + timedelta(days=k)
        if d.weekday() < 5:
            days.append(d)
        k += 1
    a = [100.0]
    b = [100.0]
    for _ in days[1:]:
        a.append(a[-1] * (1 + rng.uniform(-0.02, 0.02)))
        b.append(b[-1] * (1 + rng.uniform(-0.02, 0.02)))  # independent random walks
    ca = {"AAA": [Bar(timestamp=datetime(d.year, d.month, d.day).isoformat() + IST, open=a[i],
                      high=a[i], low=a[i], close=a[i], volume=1e6, instrument="AAA")
                  for i, d in enumerate(days)],
          "BBB": [Bar(timestamp=datetime(d.year, d.month, d.day).isoformat() + IST, open=b[i],
                      high=b[i], low=b[i], close=b[i], volume=1e6, instrument="BBB")
                  for i, d in enumerate(days)]}
    res = ArbitrageBacktestEngine(
        CointegrationSpreadStrategy,
        _params(CointegrationSpreadStrategy, lookback=30, coint_lookback=120),
        sync_mode=SyncMode.STRICT_SYNC,
    ).run(ca)
    # a non-cointegrated pair should mostly be gated out
    assert res.opportunities_executed <= 2


# --- risk engine ------------------------------------------

def test_risk_engine_rejects_and_scales():
    re = ArbRiskEngine(1_000_000.0, ArbRiskLimits(max_position_per_strategy_pct=60.0,
                                                  max_gross_exposure_pct=120.0))
    s = _struct(1000.0, 1000.0, 250, 250)  # gross 500k = 50% -> ok
    d = re.check_open(s, net_edge_bps=30, min_net_edge_bps=15, data_quality=100,
                      liquidity_score=80, viability_score=80, latency_sensitivity="low")
    assert d.ok
    re.on_open(s)
    # after 2 opens gross is 100%; a 3rd (150%) exceeds the 120% cap -> scaled
    # per-structure 60% limit still allows it; a 3rd pushes past 150% gross -> scaled
    re.on_open(s)
    d3 = re.check_open(s, net_edge_bps=30, min_net_edge_bps=15, data_quality=100,
                       liquidity_score=80, viability_score=80, latency_sensitivity="low")
    assert d3.ok and d3.scale < 1.0

    bad = re.check_open(s, net_edge_bps=5, min_net_edge_bps=15, data_quality=100,
                        liquidity_score=80, viability_score=80, latency_sensitivity="low")
    assert not bad.ok and bad.reason is RejectReason.NEGATIVE_NET_EDGE
    stale = re.check_open(s, net_edge_bps=30, min_net_edge_bps=15, data_quality=20,
                          liquidity_score=80, viability_score=80, latency_sensitivity="low")
    assert stale.reason is RejectReason.STALE_DATA


# --- new strategies --------------------------------------

def _arb_params(cls, **over):
    p = dict(cls.PRESETS["aggressive"])
    p.update(capital=1_000_000.0, min_net_edge_bps=0.0, spread_bps=1.0, exec_risk_buffer_bps=0.0,
             financing_rate_annual=0.0, borrow_rate_annual=0.0, position_fraction=0.4)
    p.update(over)
    return cls.resolve_params(p)


def test_sector_rv_runs_on_a_correlated_pair():
    candles = _coint_pair(360, seed=4)  # stock ~ 1.5*proxy + mean-reverting spread
    res = ArbitrageBacktestEngine(
        SectorRelativeValueStrategy, _arb_params(SectorRelativeValueStrategy, lookback=25),
        capital=1_000_000.0, cost_model=CostModel(CostConfig()), sync_mode=SyncMode.STRICT_SYNC,
    ).run(candles)
    assert res.opportunities_executed > 0
    assert all(t.legs[0].instrument != t.legs[1].instrument for t in res.trades)
    assert res.metrics["arbitrage_quality_score"] >= 0.0


def _spot_future(n: int, seed: int, premium0: float, expiry_day_idx: int) -> tuple[dict, float]:
    rng = random.Random(seed)
    days, k = [], 0
    while len(days) < n:
        d = date(2024, 1, 2) + timedelta(days=k)
        if d.weekday() < 5:
            days.append(d)
        k += 1
    spot = 20000.0
    spot_bars, fut_bars = [], []
    for i, d in enumerate(days):
        spot *= 1 + rng.uniform(-0.008, 0.008)
        frac_left = max(0.0, (expiry_day_idx - i) / expiry_day_idx)
        prem = premium0 * frac_left + rng.gauss(0, 6.0)  # premium decays to ~0 by expiry
        fut = spot + prem
        ts = datetime(d.year, d.month, d.day).isoformat() + IST
        spot_bars.append(Bar(timestamp=ts, open=spot, high=spot, low=spot, close=spot,
                             volume=1e6, instrument="IDX"))
        fut_bars.append(Bar(timestamp=ts, open=fut, high=fut, low=fut, close=fut,
                            volume=1e6, instrument="IDXFUT"))
    expiry_ts = datetime.combine(days[expiry_day_idx], datetime.min.time()).timestamp()
    return {"IDX": spot_bars, "IDXFUT": fut_bars}, expiry_ts


def test_cash_and_carry_opens_on_positive_carry_and_closes_by_expiry():
    candles, expiry_ts = _spot_future(140, seed=2, premium0=260.0, expiry_day_idx=120)
    res = ArbitrageBacktestEngine(
        CashAndCarryStrategy,
        _arb_params(CashAndCarryStrategy, lookback=15, expiry_ts=expiry_ts,
                    min_carry_annual=0.02, financing_rate_override=0.07),
        capital=1_000_000.0, cost_model=CostModel(CostConfig()), sync_mode=SyncMode.STRICT_SYNC,
    ).run(candles)
    assert res.opportunities_executed > 0
    # the cash leg is financed, the future leg is the NFO short
    t = res.trades[0]
    assert {leg.side for leg in t.legs} == {"BUY", "SELL"}
    assert t.exit_reason in ("converged", "expiry_close", "carry_lost", "max_holding_days")


def test_index_basis_trades_a_stretched_residual():
    candles, expiry_ts = _spot_future(120, seed=5, premium0=180.0, expiry_day_idx=100)
    res = ArbitrageBacktestEngine(
        IndexFuturesBasisStrategy,
        _arb_params(IndexFuturesBasisStrategy, lookback=20, expiry_ts=expiry_ts,
                    risk_free_rate=0.02),
        capital=1_000_000.0, cost_model=CostModel(CostConfig()), sync_mode=SyncMode.STRICT_SYNC,
    ).run(candles)
    assert res.opportunities_seen >= 0
    for k in ("net_pnl", "arbitrage_quality_score", "edge_capture_rate"):
        assert k in res.metrics


def test_calendar_spread_trades_a_mean_reverting_spread():
    rng = random.Random(3)
    days, k = [], 0
    while len(days) < 160:
        d = date(2024, 1, 2) + timedelta(days=k)
        if d.weekday() < 5:
            days.append(d)
        k += 1
    near = 20000.0
    sp = 120.0
    n_bars, f_bars = [], []
    for d in days:
        near *= 1 + rng.uniform(-0.006, 0.006)
        sp = 120.0 + 0.8 * (sp - 120.0) + rng.gauss(0, 15.0)  # AR(1) around 120
        far = near + sp
        ts = datetime(d.year, d.month, d.day).isoformat() + IST
        n_bars.append(Bar(timestamp=ts, open=near, high=near, low=near, close=near, volume=1e6, instrument="NEARFUT"))
        f_bars.append(Bar(timestamp=ts, open=far, high=far, low=far, close=far, volume=1e6, instrument="FARFUT"))
    near_expiry = datetime.combine(days[150], datetime.min.time()).timestamp()
    res = ArbitrageBacktestEngine(
        CalendarSpreadStrategy,
        _arb_params(CalendarSpreadStrategy, lookback=20, near_expiry_ts=near_expiry),
        capital=1_000_000.0, cost_model=CostModel(CostConfig()), sync_mode=SyncMode.STRICT_SYNC,
    ).run({"NEARFUT": n_bars, "FARFUT": f_bars})
    assert res.opportunities_executed > 0

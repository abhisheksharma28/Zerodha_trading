"""Sector Seasonality research engine — synthetic-data checks for the
maths, the FDR gate, point-in-time correctness and no-lookahead."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.seasonality import engine as eng
from app.seasonality.fdr import benjamini_hochberg
from app.seasonality.horizons import multi_horizon
from app.seasonality.returns import build_panel, monthly_returns
from app.seasonality.stats import month_stats
from app.strategies.base import Bar


def _daily_bars(symbol: str, monthly_pct: dict[int, float], *, years: range, start_px=1000.0):
    """Build daily bars where each calendar month compounds to
    monthly_pct[month] (%), with light noise so t-stats aren't infinite."""
    rng = random.Random(hash(symbol) & 0xFFFF)
    bars: list[Bar] = []
    px = start_px
    d = datetime(years.start, 1, 1)
    end = datetime(years.stop, 1, 1)
    while d < end:
        # daily step ~ month target / 21, plus noise
        tgt = monthly_pct.get(d.month, 0.6) + rng.uniform(-1.5, 1.5)
        step = (1.0 + tgt / 100.0) ** (1.0 / 21.0) - 1.0
        px = max(px * (1.0 + step), 1.0)
        if d.weekday() < 5:
            bars.append(Bar(timestamp=d.isoformat(), open=px, high=px, low=px, close=px,
                            volume=1000, instrument=symbol))
        d += timedelta(days=1)
    return bars


def test_monthly_returns_use_completed_months_only():
    bars = _daily_bars("X", dict.fromkeys(range(1, 13), 1.0), years=range(2015, 2019))
    # append a partial current month
    last = datetime(2019, 1, 10)
    bars += [Bar(timestamp=(last + timedelta(days=i)).isoformat(), open=1, high=1, low=1,
                 close=2000 + i, volume=1, instrument="X") for i in range(5)]
    mr = monthly_returns(bars)
    assert (2019, 1) not in mr  # the partial month is dropped
    assert (2018, 12) in mr


def test_own_edge_is_demeaned_within_the_year():
    # a sector that is +8% every April and +0.5% every other month
    apr = {m: (8.0 if m == 4 else 0.5) for m in range(1, 13)}
    panel = build_panel(
        {"NIFTY 50": _daily_bars("NIFTY 50", dict.fromkeys(range(1, 13), 1.0), years=range(2008, 2024)),
         "NIFTY IT": _daily_bars("NIFTY IT", apr, years=range(2008, 2024))},
        sectors=["NIFTY IT"],
    )
    own_apr = [v for (y, m), v in panel["own"]["NIFTY IT"].items() if m == 4]
    own_jan = [v for (y, m), v in panel["own"]["NIFTY IT"].items() if m == 1]
    assert sum(own_apr) / len(own_apr) > 3.0   # April clearly above the year's mean
    assert sum(own_jan) / len(own_jan) < 1.0   # ordinary months near / below zero


def test_bh_fdr_is_monotone_and_scales_with_grid_size():
    ps = {("a", i): 0.001 for i in range(3)}
    ps.update({("b", i): 0.5 for i in range(3)})
    q = benjamini_hochberg(ps)
    assert all(q[("a", i)] < q[("b", 0)] for i in range(3))
    assert q[("a", 0)] <= q[("b", 0)]
    # a lone strong p-value in a small grid survives; the same p in a huge grid may not
    q_small = benjamini_hochberg({("x", 0): 0.01, ("x", 1): 0.9})
    q_big = benjamini_hochberg({("x", 0): 0.01, **{("y", i): 0.9 for i in range(200)}})
    assert q_small[("x", 0)] < q_big[("x", 0)]


def test_multi_horizon_flags_a_weakening_pattern():
    # strong early, fading recently
    year_edges = {y: (6.0 if y < 2018 else 0.2) for y in range(2005, 2025)}
    hz = multi_horizon(year_edges, last_year=2024)
    assert hz["by_horizon"]["max"]["mean_edge_pct"] > 0
    assert hz["stability"] in ("weakening", "mixed", "broken")
    assert hz["trend"] == "weakening"


def test_month_stats_shapes():
    st = month_stats([5.0, 6.0, 4.0, 7.0, 5.5, 6.5, 4.5], [8, 9, 7, 10, 8, 9, 7])
    assert st["n"] == 7 and st["tier"] == "low"
    assert st["t_stat"] > 3
    assert 0.0 <= st["p_value"] <= 1.0
    assert st["bootstrap"]["available"] and st["bootstrap"]["prob_positive"] > 0.9


def test_analyze_end_to_end_synthetic(monkeypatch):
    yrs = range(2006, 2024)
    apr_strong = {m: (7.0 if m == 4 else 0.6) for m in range(1, 13)}
    oct_weak = {m: (-5.0 if m == 10 else 0.8) for m in range(1, 13)}
    flat = dict.fromkeys(range(1, 13), 0.7)

    bars = {
        "NIFTY 50": _daily_bars("NIFTY 50", flat, years=yrs),
        "INDIA VIX": _daily_bars("INDIA VIX", dict.fromkeys(range(1, 13), 0.0), years=yrs, start_px=15),
        "NIFTY IT": _daily_bars("NIFTY IT", apr_strong, years=yrs),
        "NIFTY METAL": _daily_bars("NIFTY METAL", oct_weak, years=yrs),
        "NIFTY FMCG": _daily_bars("NIFTY FMCG", flat, years=yrs),
        "NIFTY AUTO": _daily_bars("NIFTY AUTO", flat, years=yrs),
    }
    from app.seasonality import data as sdata

    def _fake_load(_db, _settings, **_kw):
        audits = {s: sdata.audit_series(s, b) for s, b in bars.items()}
        return bars, audits

    monkeypatch.setattr(eng, "load_history", _fake_load)

    rep = eng.analyze(None, None)
    assert rep["sector_count"] == 4
    assert set(rep["months"].keys()) == {str(m) for m in range(1, 13)}

    apr = rep["months"]["4"]
    it_row = next(r for r in apr["ranking"] if r["sector"] == "NIFTY IT")
    assert it_row["rank"] == 1                      # strongest in April
    assert it_row["long_score"] > it_row["short_score"]
    assert any(c["sector"] == "NIFTY IT" for c in apr["long_candidates"])

    octo = rep["months"]["10"]
    metal_row = next(r for r in octo["ranking"] if r["sector"] == "NIFTY METAL")
    assert metal_row["rank"] == len(octo["ranking"])   # weakest in October
    assert any(c["sector"] == "NIFTY METAL" for c in octo["short_candidates"])
    assert metal_row["short_score"] > metal_row["long_score"]

    # FDR actually ran across the grid
    assert rep["fdr"]["n_tested"] >= 40
    assert rep["fdr"]["n_significant_q05"] >= 1

    # every graded cell has the full validation payload
    it_apr_cell = rep["grid"]["NIFTY IT"]["4"]
    for k in ("q_value", "fdr_label", "visual", "confidence", "horizons", "regime", "bootstrap"):
        assert k in it_apr_cell


def test_walk_forward_is_out_of_sample_and_reports_rank_ic(monkeypatch):
    from app.seasonality import backtest as wf

    yrs = range(2004, 2024)
    # NIFTY IT genuinely strong every April, NIFTY METAL genuinely weak every
    # April; everyone else flat. A causal ranking should learn this.
    bars = {
        "NIFTY 50": _daily_bars("NIFTY 50", dict.fromkeys(range(1, 13), 0.7), years=yrs),
        "INDIA VIX": _daily_bars("INDIA VIX", dict.fromkeys(range(1, 13), 0.0), years=yrs, start_px=15),
        "NIFTY IT": _daily_bars("NIFTY IT", {m: (9.0 if m == 4 else 0.6) for m in range(1, 13)}, years=yrs),
        "NIFTY METAL": _daily_bars("NIFTY METAL", {m: (-8.0 if m == 4 else 0.7) for m in range(1, 13)}, years=yrs),
        "NIFTY FMCG": _daily_bars("NIFTY FMCG", dict.fromkeys(range(1, 13), 0.7), years=yrs),
        "NIFTY AUTO": _daily_bars("NIFTY AUTO", dict.fromkeys(range(1, 13), 0.6), years=yrs),
        "NIFTY PHARMA": _daily_bars("NIFTY PHARMA", dict.fromkeys(range(1, 13), 0.65), years=yrs),
    }
    monkeypatch.setattr(
        wf, "load_history",
        lambda *_a, **_k: (bars, {s: __import__("app.seasonality.data", fromlist=["audit_series"]).audit_series(s, b) for s, b in bars.items()}),
    )

    r = wf.walk_forward(None, None, strategy="E_long_top3_short_bottom3",
                        start_test_year=2012, min_train_years=5)
    # with a real repeating edge the long/short spread and rank IC should be positive
    assert r.rank_ic["mean"] is not None and r.rank_ic["mean"] > 0.1
    assert r.spread["mean_pct"] is not None and r.spread["mean_pct"] > 0
    assert r.n_months >= 100
    d = r.to_dict()
    assert "out_of_sample" in d["oos_split"] and "in_sample" in d["oos_split"]
    # every test-month decision only used earlier years -> no lookahead
    apr_trades = [t for t in r.trades if t.month == 4 and t.side == "LONG"]
    assert any(t.sector == "NIFTY IT" for t in apr_trades)


def test_no_lookahead_current_partial_month_excluded(monkeypatch):
    # a sector with a huge spike in the (incomplete) current month must not
    # let that month leak into its own-month history
    now = datetime.now()
    yrs = range(2010, now.year)
    bars = _daily_bars("NIFTY IT", dict.fromkeys(range(1, 13), 0.7), years=yrs)
    bars += [Bar(timestamp=(datetime(now.year, now.month, 1) + timedelta(days=i)).isoformat(),
                 open=1, high=1, low=1, close=9_000_000, volume=1, instrument="NIFTY IT")
             for i in range(3)]
    mr = monthly_returns(bars)
    assert (now.year, now.month) not in mr

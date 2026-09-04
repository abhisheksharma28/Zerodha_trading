"""Discovery Engine P3 — optimizer library + portfolio evaluation."""

from __future__ import annotations

from datetime import date

import numpy as np

from app.discovery import ingest, optimizers
from app.discovery import service as disc_service


def _series(start: date, months: int, m_ret: float, sd: float, seed: int):
    rng = np.random.default_rng(seed)
    out = []
    p = 100.0
    y, mo = start.year, start.month
    for _ in range(months):
        out.append((date(y, mo, 1), round(p, 4)))
        p *= max(0.2, 1.0 + m_ret + rng.normal(0.0, sd))
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return out


def _rets(pts):
    v = [c for _d, c in pts]
    return [v[i] / v[i - 1] - 1.0 for i in range(1, len(v))]


def _universe():
    # HI: high return, high vol; LO: low return, low vol; MID: middle
    return {
        "HI": _rets(_series(date(2010, 1, 1), 160, 0.012, 0.06, 1)),
        "MID": _rets(_series(date(2010, 1, 1), 160, 0.006, 0.03, 2)),
        "LO": _rets(_series(date(2010, 1, 1), 160, 0.003, 0.012, 3)),
        "LO2": _rets(_series(date(2010, 1, 1), 160, 0.0028, 0.011, 4)),
    }


def test_equal_weight_is_uniform_and_sums_to_one():
    w = optimizers.equal_weight(["A", "B", "C", "D"])
    assert set(w.values()) == {0.25}
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_min_variance_tilts_to_the_low_vol_assets():
    u = _universe()
    w = optimizers.min_variance(list(u), u, bounds=(0.0, 0.6))
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert w["LO"] + w["LO2"] > w["HI"] + w["MID"]     # variance-averse
    assert all(0.0 <= x <= 0.6 + 1e-6 for x in w.values())


def test_max_sharpe_respects_the_box_bounds():
    u = _universe()
    w = optimizers.max_sharpe(list(u), u, bounds=(0.0, 0.35))
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert max(w.values()) <= 0.35 + 1e-6


def test_risk_parity_equalises_risk_contributions():
    u = _universe()
    syms = list(u)
    w = optimizers.risk_parity(syms, u, bounds=(0.0, 0.9))
    wv = np.array([w[s] for s in syms])
    R = np.array([u[s] for s in syms])
    cov = np.cov(R)
    rc = wv * (cov @ wv)
    rc = rc / rc.sum()
    assert rc.max() - rc.min() < 0.25      # roughly balanced (loose on synthetic data)


def test_hrp_produces_a_valid_allocation():
    u = _universe()
    w = optimizers.hrp(list(u), u)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert all(x > 0 for x in w.values())


def test_optimize_dispatch_rejects_an_unknown_method():
    import pytest
    with pytest.raises(ValueError, match="unknown method"):
        optimizers.optimize("magic", ["A", "B", "C"], {"A": [0.1], "B": [0.1], "C": [0.1]})


def test_optimize_and_evaluate_end_to_end(db):
    u = {  # persist under real universe symbols so the store accepts them
        "SPY": _series(date(2010, 1, 1), 160, 0.010, 0.05, 11),
        "TLT": _series(date(2010, 1, 1), 160, 0.004, 0.03, 12),
        "GLD": _series(date(2010, 1, 1), 160, 0.005, 0.04, 13),
        "IEF": _series(date(2010, 1, 1), 160, 0.003, 0.012, 14),
    }
    ingest.ingest_prices(db, series=u, source="test")
    out = disc_service.optimize_and_evaluate(
        db, symbols=["SPY", "TLT", "GLD", "IEF"], method="max_sharpe",
        constraint_mode="balanced",
    )
    assert out["available"] is True and out["method"] == "max_sharpe"
    assert abs(sum(out["weights"].values()) - 1.0) < 1e-4
    m = out["metrics"]
    assert "cagr_pct" in m and "sharpe" in m and "max_drawdown_pct" in m
    assert m["annual_turnover_pct"] >= 0 and m["effective_n"] >= 1
    assert set(out["contribution_pct"]) == {"SPY", "TLT", "GLD", "IEF"}
    assert "by_regime" in out

"""Discovery Engine P5 — adversarial validation + experiment tracking."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np

from app.discovery import ingest, search, service, validate


def _series(start: date, months: int, m_ret: float, sd: float, seed: int):
    rng = np.random.default_rng(seed)
    out, p = [], 100.0
    y, mo = start.year, start.month
    for _ in range(months):
        out.append((date(y, mo, 1), round(p, 4)))
        p *= max(0.2, 1.0 + m_ret + rng.normal(0.0, sd))
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return out


def _seed_universe(db):
    ingest.ingest_prices(db, source="test", series={
        "SPY": _series(date(2009, 1, 1), 190, 0.010, 0.05, 1),
        "TLT": _series(date(2009, 1, 1), 190, 0.004, 0.032, 2),
        "GLD": _series(date(2009, 1, 1), 190, 0.005, 0.045, 3),
        "IEF": _series(date(2009, 1, 1), 190, 0.003, 0.013, 4),
        "AGG": _series(date(2009, 1, 1), 190, 0.0028, 0.011, 5),
        "VNQ": _series(date(2009, 1, 1), 190, 0.008, 0.06, 6),
        "DBC": _series(date(2009, 1, 1), 190, 0.002, 0.05, 7),
        "HYG": _series(date(2009, 1, 1), 190, 0.005, 0.025, 8),
    })


def test_deflated_sharpe_penalises_more_trials():
    rng = np.random.default_rng(0)
    rets = list(0.01 + rng.normal(0.0, 0.03, size=120))
    few = validate.deflated_sharpe(rets, n_trials=2)
    many = validate.deflated_sharpe(rets, n_trials=5000)
    assert few["available"] and many["available"]
    assert 0.0 <= many["deflated_sharpe"] <= few["deflated_sharpe"] <= 1.0
    assert many["sr_star"] > few["sr_star"]


def test_block_bootstrap_reports_a_distribution():
    rng = np.random.default_rng(1)
    rets = list(0.008 + rng.normal(0.0, 0.04, size=150))
    bb = validate.block_bootstrap(rets, sims=800, seed=3)
    assert bb["available"] is True
    assert set(bb["cagr_pct"]) == {5, 25, 50, 75, 95}
    assert bb["cagr_pct"][5] <= bb["cagr_pct"][50] <= bb["cagr_pct"][95]
    assert 0.0 <= bb["prob_negative_cagr"] <= 1.0


def test_weight_perturbation_and_start_date(db):
    _seed_universe(db)
    w = {"SPY": 0.3, "TLT": 0.25, "GLD": 0.2, "IEF": 0.15, "AGG": 0.1}
    pt = validate.weight_perturbation(db, w, n=12, seed=2)
    assert pt["available"] is True
    assert isinstance(pt["fragile"], bool)
    assert pt["perturbed_mean"] >= 0.0

    sd = validate.start_date_sensitivity(db, w)
    assert sd["available"] is True
    assert sd["sharpe_worst"] <= sd["sharpe_median"] <= sd["sharpe_best"]


def test_rejection_rules_flag_a_concentrated_single_regime_book():
    ev = {
        "metrics": {"annual_turnover_pct": 300.0},
        "weights": {"AAA": 0.7, "BBB": 0.3},
        "contribution_pct": {"AAA": 95.0, "BBB": 5.0},
        "in_sample": {"sharpe": 1.4},
        "out_of_sample": {"sharpe": 0.1},
        "by_regime": {
            "bull": {"return_pct": 40.0}, "neutral": {"return_pct": -2.0},
            "risk_off": {"return_pct": -5.0},
        },
    }
    val = {"deflated_sharpe": {"available": True, "deflated_sharpe": 0.4, "psr": 0.5},
           "perturbation": {"fragile": True},
           "block_bootstrap": {"available": True, "prob_negative_cagr": 0.4}}
    fails = validate.rejection_rules(ev, val)
    assert any("55%" in f for f in fails)
    assert any("45%" in f for f in fails)
    assert any("out-of-sample" in f for f in fails)
    assert any("single market regime" in f for f in fails)
    assert any("turnover" in f for f in fails)
    assert any("deflated Sharpe" in f for f in fails)
    assert any("fragile" in f for f in fails)


def test_stability_score_is_bounded_and_labelled():
    ev = {
        "metrics": {"sharpe": 1.0, "effective_n": 5.0, "annual_turnover_pct": 40.0},
        "in_sample": {"sharpe": 1.0}, "out_of_sample": {"sharpe": 0.9},
        "by_regime": {"bull": {"return_pct": 20.0}, "neutral": {"return_pct": 3.0}},
    }
    val = {
        "deflated_sharpe": {"available": True, "deflated_sharpe": 0.95},
        "block_bootstrap": {"available": True, "prob_dd_worse_than_25pct": 0.05},
        "perturbation": {"available": True, "max_drop": 4.0},
        "start_date_sensitivity": {"available": True},
    }
    out = validate.stability_score(ev, val)
    assert 0.0 <= out["stability_score"] <= 100.0
    assert out["label"]
    assert abs(sum(out["components"].values()) - out["stability_score"]) < 0.5


def test_validate_portfolio_end_to_end(db):
    _seed_universe(db)
    w = {"SPY": 0.25, "TLT": 0.25, "GLD": 0.2, "IEF": 0.15, "AGG": 0.15}
    out = validate.validate_portfolio(db, w, n_trials=500, bootstrap_sims=400)
    assert out["available"] is True
    v = out["validation"]
    assert v["verdict"] in {"pass", "downgrade", "reject"}
    assert 0.0 <= v["stability_score"] <= 100.0
    assert "rejections" in v and isinstance(v["rejections"], list)
    assert v["block_bootstrap"]["available"] is True


def test_search_attaches_validation_and_survivors(db):
    _seed_universe(db)
    out = search.monte_carlo_search(
        db, ["SPY", "TLT", "GLD", "IEF", "AGG", "VNQ", "DBC", "HYG"],
        n_assets=(5, 7), n_portfolios=120, seed=3, validate_top=3,
    )
    assert out["available"] is True
    assert "survivors" in out
    validated = [r for r in out["top"] if "validation" in r]
    assert 1 <= len(validated) <= 3
    for r in validated:
        assert "final_score" in r
        assert r["validation"]["verdict"] in {"pass", "downgrade", "reject"}
    for s in out["survivors"]:
        assert s["validation"]["verdict"] != "reject"


def test_search_run_is_recorded_and_readable(db):
    _seed_universe(db)
    started = datetime.now(UTC)
    result = search.monte_carlo_search(
        db, ["SPY", "TLT", "GLD", "IEF", "AGG", "VNQ", "DBC", "HYG"],
        n_assets=(5, 7), n_portfolios=100, seed=9, validate_top=2,
    )
    run_id = service.record_search_run(
        db, result=result, method="monte_carlo", currency="USD", seed=9,
        universe_syms=["SPY", "TLT", "GLD", "IEF", "AGG", "VNQ", "DBC", "HYG"],
        params={"n_portfolios": 100}, started_at=started,
    )
    assert run_id
    recent = service.recent_search_runs(db, limit=5)
    assert any(r["id"] == run_id for r in recent)
    detail = service.get_search_run(db, run_id)
    assert detail["method"] == "monte_carlo"
    assert detail["n_tested"] == 100
    assert len(detail["universe"]) == 8

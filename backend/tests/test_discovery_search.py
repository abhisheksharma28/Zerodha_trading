"""Discovery Engine P4 — fitness, Monte Carlo + genetic search, Pareto."""

from __future__ import annotations

from datetime import date

import numpy as np

from app.discovery import fitness, ingest, search


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


def test_fitness_score_is_bounded_and_has_all_categories():
    ev = {
        "metrics": {"sharpe": 1.2, "sortino": 1.6, "omega": 1.8, "cagr_pct": 10.0,
                    "max_drawdown_pct": -18.0, "ulcer_index": 8.0,
                    "positive_period_pct": 62.0, "rolling_return_std_pct": 9.0,
                    "effective_n": 5.0, "corr_to_market": 0.4,
                    "annual_turnover_pct": 60.0},
        "in_sample": {"sharpe": 1.1}, "out_of_sample": {"sharpe": 1.0},
        "weights": {"A": 0.3, "B": 0.3, "C": 0.4},
    }
    s = fitness.score(ev)
    assert 0.0 <= s["alpha_score"] <= 100.0
    assert set(s["category_scores"]) == set(fitness.DEFAULT_WEIGHTS)


def test_pareto_frontier_picks_the_non_dominated():
    evals = [
        {"metrics": {"cagr_pct": 12, "sharpe": 1.0, "max_drawdown_pct": -20, "effective_n": 5, "sortino": 1.2}},
        {"metrics": {"cagr_pct": 10, "sharpe": 0.9, "max_drawdown_pct": -18, "effective_n": 4, "sortino": 1.0}},  # dominated by [0]
        {"metrics": {"cagr_pct": 8, "sharpe": 1.4, "max_drawdown_pct": -10, "effective_n": 6, "sortino": 1.5}},
    ]
    front = set(fitness.pareto_frontier(evals))
    assert front == {0, 2}


def test_monte_carlo_search_returns_ranked_portfolios(db):
    _seed_universe(db)
    out = search.monte_carlo_search(
        db, ["SPY", "TLT", "GLD", "IEF", "AGG", "VNQ", "DBC", "HYG"],
        n_assets=(5, 7), n_portfolios=300, seed=3,
    )
    assert out["available"] is True and out["tested"] == 300
    assert 1 <= len(out["top"]) <= 10
    scores = [p["alpha_score"] for p in out["top"]]
    assert scores == sorted(scores, reverse=True)
    for p in out["top"]:
        assert 5 <= len(p["weights"]) <= 7
        assert abs(sum(p["weights"].values()) - 1.0) < 1e-3
        assert max(p["weights"].values()) <= 0.35 + 1e-6
    assert len(out["pareto_frontier"]) >= 1

    # deterministic given the seed
    again = search.monte_carlo_search(
        db, ["SPY", "TLT", "GLD", "IEF", "AGG", "VNQ", "DBC", "HYG"],
        n_assets=(5, 7), n_portfolios=300, seed=3,
    )
    assert again["top"][0]["weights"] == out["top"][0]["weights"]


def test_genetic_search_converges_to_a_valid_portfolio(db):
    _seed_universe(db)
    out = search.genetic_search(
        db, ["SPY", "TLT", "GLD", "IEF", "AGG", "VNQ", "DBC", "HYG"],
        n_assets=(5, 8), generations=8, population=16, seed=5,
    )
    assert out["available"] is True and out["method"] == "genetic"
    assert out["tested"] > 16
    best = out["top"][0]
    assert 5 <= len(best["weights"]) <= 8
    assert abs(sum(best["weights"].values()) - 1.0) < 1e-3
    assert "category_scores" in best and "by_regime" in best

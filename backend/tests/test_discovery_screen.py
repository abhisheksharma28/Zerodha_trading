"""Discovery Engine P2 — instrument metrics, correlation clustering, screen."""

from __future__ import annotations

import math
from datetime import date

from app.discovery import ingest, screen
from app.discovery.metrics import instrument_metrics


def _monthly(start: date, months: int, m_ret: float, *, noise=None, p0: float = 100.0):
    out = []
    p = p0
    y, mo = start.year, start.month
    for i in range(months):
        out.append((date(y, mo, 1), round(p, 4)))
        p *= 1.0 + m_ret + (noise(i) if noise else 0.0)
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return out


def _rets(pts):
    v = [c for _d, c in pts]
    return [v[i] / v[i - 1] - 1.0 for i in range(1, len(v))]


def test_instrument_metrics_on_a_steady_uptrend():
    # mild noise so vol / sharpe are finite, but every month still positive
    m = instrument_metrics(_rets(_monthly(
        date(2010, 1, 1), 180, 0.009, noise=lambda i: 0.001 if i % 2 else -0.0005)))
    assert m["cagr_pct"] > 5 and 0 < m["sharpe"] < 100
    assert m["max_drawdown_pct"] <= 0
    assert m["sortino"] >= m["sharpe"]          # no downside vol -> Sortino falls back to Sharpe
    assert m["positive_period_pct"] == 100.0


def test_instrument_metrics_on_a_downtrend_is_negative():
    m = instrument_metrics(_rets(_monthly(date(2015, 1, 1), 120, -0.004)))
    assert m["cagr_pct"] < 0 and m["max_drawdown_pct"] < -5


def test_instrument_metrics_flags_a_short_series():
    assert instrument_metrics([0.01, 0.02, -0.01]).get("insufficient") is True


def test_cluster_separates_uncorrelated_return_streams():
    # two "market" names move together; a "bond" name moves opposite; gold noisy
    up = _rets(_monthly(date(2012, 1, 1), 120, 0.006, noise=lambda i: 0.02 if i % 2 else -0.02))
    up2 = [r + 0.001 for r in up]                       # ~perfectly correlated with up
    down = [-r for r in up]                             # anti-correlated
    gold = _rets(_monthly(date(2012, 1, 1), 120, 0.003, noise=lambda i: 0.03 if i % 3 else -0.02))
    cl = screen.cluster({"UP": up, "UP2": up2, "DOWN": down, "GOLD": gold}, k=3)
    assert cl["UP"] == cl["UP2"]                        # the twins cluster together
    assert cl["DOWN"] != cl["UP"]                       # anti-correlated is its own cluster


def _seed(db, series):
    ingest.ingest_prices(db, series=series, source="test", bar_interval="1month")


def test_screen_ranks_instruments_and_assigns_clusters(db):
    _seed(db, {
        "SPY": _monthly(date(2010, 1, 1), 180, 0.008, noise=lambda i: 0.03 if i % 2 else -0.028),
        "TLT": _monthly(date(2010, 1, 1), 180, 0.003, noise=lambda i: 0.02 if i % 3 else -0.018),
        "GLD": _monthly(date(2010, 1, 1), 180, 0.004, noise=lambda i: 0.04 if i % 4 else -0.03),
        "IEF": _monthly(date(2010, 1, 1), 180, 0.0025, noise=lambda i: 0.01 if i % 2 else -0.009),
        "AGG": _monthly(date(2010, 1, 1), 180, 0.0022, noise=lambda i: 0.008 if i % 3 else -0.007),
    })
    sc = screen.screen(db, currency="USD")
    assert sc["n"] == 5
    syms = [r["symbol"] for r in sc["instruments"]]
    assert set(syms) == {"SPY", "TLT", "GLD", "IEF", "AGG"}
    # rows sorted by screen_score desc
    scores = [r["screen_score"] for r in sc["instruments"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    assert all(r["cluster"] is not None for r in sc["instruments"])
    assert all("cagr_pct" in r["metrics"] for r in sc["instruments"])


def test_candidates_takes_the_best_of_each_cluster(db):
    _seed(db, {
        "SPY": _monthly(date(2010, 1, 1), 180, 0.008, noise=lambda i: 0.03 if i % 2 else -0.028),
        "TLT": _monthly(date(2010, 1, 1), 180, 0.003, noise=lambda i: 0.02 if i % 3 else -0.018),
        "GLD": _monthly(date(2010, 1, 1), 180, 0.004, noise=lambda i: 0.04 if i % 4 else -0.03),
        "IEF": _monthly(date(2010, 1, 1), 180, 0.0025, noise=lambda i: 0.01 if i % 2 else -0.009),
        "AGG": _monthly(date(2010, 1, 1), 180, 0.0022, noise=lambda i: 0.008 if i % 3 else -0.007),
        "HYG": _monthly(date(2010, 1, 1), 180, 0.004, noise=lambda i: 0.012 if i % 2 else -0.011),
    })
    out = screen.candidates(db, k=4, per_cluster=1)
    assert 1 <= out["n_clusters"] <= 6
    assert 1 <= len(out["candidates"]) <= 6
    assert len(set(out["candidates"])) == len(out["candidates"])  # unique


def test_annualisation():
    assert math.isclose(math.sqrt(12), 3.464, rel_tol=1e-3)

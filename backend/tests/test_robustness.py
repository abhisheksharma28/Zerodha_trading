"""Pure robustness math: Monte Carlo, walk-forward windows, sensitivity."""

from __future__ import annotations

from datetime import date

from app.backtesting.robustness import (
    SweepPoint,
    monte_carlo,
    sensitivity_verdict,
    walk_forward_summary,
    walk_forward_windows,
)


def test_monte_carlo_needs_enough_trades():
    r = monte_carlo([1.0, 2.0], initial_capital=100_000.0)
    assert r["available"] is False


def test_monte_carlo_is_deterministic_and_well_shaped():
    pnls = [500.0, -300.0, 800.0, -200.0, -400.0, 1200.0, -150.0, 300.0, -600.0, 250.0] * 5
    a = monte_carlo(pnls, initial_capital=100_000.0, n_sims=500, seed=7)
    b = monte_carlo(pnls, initial_capital=100_000.0, n_sims=500, seed=7)
    assert a == b
    bs = a["bootstrap"]["return_pct"]
    assert bs["p5"] <= bs["p50"] <= bs["p95"]
    assert 0.0 <= a["bootstrap"]["prob_loss"] <= 1.0
    assert a["bootstrap"]["prob_ruin"] == 0.0  # small pnls vs big capital


def test_monte_carlo_flags_ruin_risk_for_a_fragile_series():
    # a few huge losses relative to capital -> some resamples wipe out
    pnls = [-40_000.0, -35_000.0, 5000.0, 4000.0, 6000.0, -30_000.0, 3000.0, 2000.0]
    r = monte_carlo(pnls, initial_capital=100_000.0, n_sims=1000, seed=1)
    assert r["bootstrap"]["prob_ruin"] > 0.0


def test_walk_forward_windows_roll_forward():
    w = walk_forward_windows(date(2021, 1, 1), date(2024, 1, 1), folds=4, oos_frac=0.4)
    assert len(w) == 4
    assert w[0]["oos_end"] == w[1]["oos_start"]  # contiguous
    assert w[0]["is_start"] == "2021-01-01"
    assert w[-1]["oos_end"] <= "2024-01-01"


def test_walk_forward_windows_reject_tiny_span():
    assert walk_forward_windows(date(2024, 1, 1), date(2024, 1, 20), folds=4) == []


def test_walk_forward_summary_computes_decay():
    folds = [
        {"is_metrics": {"sharpe_ratio": 1.5, "return_pct": 20.0},
         "oos_metrics": {"sharpe_ratio": 0.4, "return_pct": 3.0}},
        {"is_metrics": {"sharpe_ratio": 1.2, "return_pct": 15.0},
         "oos_metrics": {"sharpe_ratio": -0.1, "return_pct": -2.0}},
    ]
    s = walk_forward_summary(folds)
    assert s["available"] is True
    assert s["sharpe_decay"] > 0  # OOS worse than IS
    assert s["oos_profitable_folds"] == 1
    assert s["total_folds"] == 2


def test_sensitivity_verdict_plateau_is_not_overfit():
    pts = [SweepPoint(v, 1.0 + 0.02 * abs(v - 20), 10.0, 8.0) for v in (10, 15, 20, 25, 30)]
    v = sensitivity_verdict("entry_period", pts, preset_value=20)
    assert v["available"] is True
    assert v["overfit_risk"] is False


def test_sensitivity_verdict_lone_spike_is_flagged():
    pts = [
        SweepPoint(10, 0.1, 2, 20), SweepPoint(15, 0.15, 3, 18),
        SweepPoint(20, 2.5, 40, 8),  # lone spike
        SweepPoint(25, 0.2, 4, 19), SweepPoint(30, 0.05, 1, 22),
    ]
    v = sensitivity_verdict("entry_period", pts, preset_value=20)
    assert v["overfit_risk"] is True
    assert v["best_value"] == 20


# --- orchestrator (monkeypatched backtests) --------------------

import pytest  # noqa: E402

from app.robustness import service as rob_service  # noqa: E402
from app.robustness import store as rob_store  # noqa: E402


@pytest.fixture()
def rob_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(rob_store, "_DIR", tmp_path / "rob")
    yield


def test_run_robustness_builds_payload_and_scores(rob_cache, monkeypatch, db):
    # fake run_adhoc: return metrics + a trade-pnl series that varies with the
    # swept parameter so the sensitivity surface isn't flat.
    def _fake(_db, _s, *, slug, timeframe, start, end, preset, capital, max_gross_exposure,
              max_symbols, symbols, overrides=None):
        ov = overrides or {}
        base_sharpe = 0.8 + (0.02 if ov.get("entry_period") == 25 else 0.0)
        from app.backtesting.adhoc import AdhocReport
        return AdhocReport(
            slug=slug, strategy_name=slug, preset=preset, timeframe=timeframe,
            start=start, end=end, capital=capital, requested_symbols=symbols,
            used_symbols=["AAA", "BBB"], skipped=[], parameters={},
            metrics={"return_pct": 14.0, "sharpe_ratio": base_sharpe,
                     "max_drawdown_pct": 12.0, "total_trades": 60, "win_rate_pct": 45.0},
            charts={}, equity_curve=[["2021-01-01T00:00:00+05:30", capital]],
            per_symbol=[], trades=[], data_quality={"ok": True, "warnings": []},
            caveats=[], generated_at="2024-01-01T00:00:00",
            trade_pnls=[300.0, -200.0, 500.0, -150.0, -250.0, 700.0, -100.0, 200.0] * 8,
        )

    monkeypatch.setattr(rob_service, "run_adhoc", _fake)
    payload = rob_service.run_robustness(db, None, "donchian-breakout")
    assert payload["monte_carlo"]["available"] is True
    assert payload["walk_forward"]["available"] is True
    assert payload["sensitivity"]["param"] == "entry_period"
    assert 0.0 <= payload["robustness_score"] <= 100.0
    assert rob_service.robustness_for("donchian-breakout")["slug"] == "donchian-breakout"


def test_leaderboard_folds_in_robustness_score(rob_cache, monkeypatch, db):
    from app.leaderboard import service as lb_service
    from app.leaderboard import store as lb_store

    monkeypatch.setattr(lb_store, "_DIR", (rob_store._DIR.parent / "lb"))

    # one cached canonical backtest
    from tests.test_leaderboard import _fake_report  # reuse
    monkeypatch.setattr(lb_service, "run_adhoc",
                        lambda *a, **k: _fake_report(k["slug"], ret=30.0, sharpe=1.2,
                                                     dd=15.0, trades=120))
    lb_service.run_canonical(None, None, "donchian-breakout")

    # a robustness blob that should drag the score down
    rob_store.save("donchian-breakout", {
        "slug": "donchian-breakout", "robustness_score": 20.0,
        "monte_carlo": {"available": True, "bootstrap": {"prob_ruin": 0.1, "prob_loss": 0.6}},
        "walk_forward": {"available": True, "sharpe_decay": 1.2, "oos_profitable_folds": 0,
                         "total_folds": 4},
        "sensitivity": {"available": True, "overfit_risk": True, "param": "entry_period",
                        "best_value": 25},
        "notes": [],
    })
    board = lb_service.leaderboard(db, None)
    row = next(r for r in board["rows"] if r["slug"] == "donchian-breakout")
    assert row["robustness"]["robustness_score"] == 20.0
    assert "35% of the score" in board["score_method"]

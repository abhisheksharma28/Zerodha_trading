"""Leaderboard: canonical-run caching, FIFO paper P&L, ranking, API."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.backtesting.adhoc import AdhocReport, SymbolStat
from app.leaderboard import config as lb_config
from app.leaderboard import service as lb_service
from app.leaderboard import store as lb_store
from app.leaderboard.service import _fifo_realized, leaderboard, refresh_all, run_canonical


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(lb_store, "_DIR", tmp_path / "lb")
    yield tmp_path / "lb"


def _fake_report(slug: str, *, ret: float, sharpe: float, dd: float, trades: int,
                 ruined: bool = False) -> AdhocReport:
    return AdhocReport(
        slug=slug, strategy_name=slug, preset="balanced", timeframe="1d",
        start="2021-01-01", end="2024-01-01", capital=1_000_000.0,
        requested_symbols=["NSE:AAA", "NSE:BBB"], used_symbols=["AAA", "BBB"], skipped=[],
        parameters={},
        metrics={
            "return_pct": ret, "cagr_pct": ret / 3, "sharpe_ratio": sharpe,
            "sortino_ratio": sharpe * 1.2, "calmar_ratio": (ret / max(dd, 1e-9)),
            "max_drawdown_pct": dd, "win_rate_pct": 48.0, "profit_factor": 1.3,
            "total_trades": trades, "avg_trade": 120.0, "net_pnl": ret / 100 * 1_000_000,
            "total_costs": 5000.0, "turnover_ratio": 4.0,
            "diagnostics": {"ruined": ruined, "peak_gross_exposure_pct": 95.0},
        },
        charts={"drawdown_curve": [], "monthly_returns": {}},
        equity_curve=[["2021-01-01T00:00:00+05:30", 1_000_000.0],
                      ["2024-01-01T00:00:00+05:30", 1_000_000.0 * (1 + ret / 100)]],
        per_symbol=[
            SymbolStat("AAA", trades // 2, 40000.0, 55.0, 900.0, 12000.0, -4000.0),
            SymbolStat("BBB", trades - trades // 2, -8000.0, 40.0, -200.0, 5000.0, -6000.0),
        ],
        trades=[], data_quality={"ok": True, "warnings": []},
        caveats=["research only, not investment advice"],
        generated_at="2024-01-02T00:00:00",
    )


def test_run_canonical_caches_payload(cache_dir, monkeypatch):
    monkeypatch.setattr(
        lb_service, "run_adhoc",
        lambda *a, **k: _fake_report(k["slug"], ret=42.0, sharpe=1.4, dd=12.0, trades=180),
    )
    payload = run_canonical(None, None, "donchian-breakout")
    assert payload["metrics"]["sharpe_ratio"] == 1.4
    assert payload["top_symbols"][0]["symbol"] == "AAA"
    cfg = lb_config.canonical_for("donchian-breakout")
    assert lb_store.load("donchian-breakout", cfg.config_hash)["metrics"]["return_pct"] == 42.0


def test_refresh_all_isolates_failures(cache_dir, monkeypatch):
    def _maybe(*a, **k):
        if k["slug"] == "mean-reversion":
            raise RuntimeError("kaboom")
        return _fake_report(k["slug"], ret=10.0, sharpe=0.8, dd=9.0, trades=50)

    monkeypatch.setattr(lb_service, "run_adhoc", _maybe)
    out = refresh_all(None, None, ["donchian-breakout", "mean-reversion", "multi-factor"])
    assert out["donchian-breakout"].startswith("ok:")
    assert out["mean-reversion"].startswith("error: kaboom")
    assert out["multi-factor"].startswith("ok:")


def test_leaderboard_ranks_scored_rows(cache_dir, monkeypatch, db):
    scores = {
        "donchian-breakout": {"ret": 60.0, "sharpe": 1.9, "dd": 10.0, "trades": 200},
        "trend-following": {"ret": 25.0, "sharpe": 0.9, "dd": 18.0, "trades": 140},
        "multi-factor": {"ret": 40.0, "sharpe": 1.3, "dd": 12.0, "trades": 90},
        "mean-reversion": {"ret": -5.0, "sharpe": -0.2, "dd": 30.0, "trades": 300, "ruined": True},
    }
    default = {"ret": 5.0, "sharpe": 0.3, "dd": 8.0, "trades": 20}
    monkeypatch.setattr(
        lb_service, "run_adhoc",
        lambda *a, **k: _fake_report(k["slug"], **scores.get(k["slug"], default)),
    )
    for slug in scores:
        run_canonical(None, None, slug)

    board = leaderboard(db, None)
    ranked = [r for r in board["rows"] if r.get("composite_score") is not None]
    assert ranked[0]["slug"] == "donchian-breakout"  # best Sharpe/return
    assert all(ranked[i]["composite_score"] >= ranked[i + 1]["composite_score"]
               for i in range(len(ranked) - 1))
    # ruined run is excluded from scoring
    mr = next(r for r in board["rows"] if r["slug"] == "mean-reversion")
    assert mr["composite_score"] is None and mr["backtest"]["ruined"] is True
    assert "0.50 Sharpe" in board["score_method"]


def test_live_paper_stats_none_without_a_seeded_strategy(db):
    from app.leaderboard.service import live_paper_stats

    # no Strategy row named after the template in a fresh test DB
    assert live_paper_stats(db, "donchian-breakout") is None


def test_fifo_realized_pnl_is_correct():
    now = datetime(2026, 1, 1)
    fills = [
        ("INFY", "BUY", 10, 100.0, now),
        ("INFY", "BUY", 10, 110.0, now),
        ("INFY", "SELL", 15, 120.0, now),   # closes 10@100 (+200) and 5@110 (+50)
        ("SBIN", "SELL", 5, 50.0, now),     # open short
        ("SBIN", "BUY", 5, 45.0, now),      # cover +25
    ]
    realised, closed = _fifo_realized(fills)
    assert round(realised, 2) == 275.0
    assert len(closed) == 3


def test_leaderboard_api_lists_every_template(cache_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/v1/leaderboard")
        assert r.status_code == 200
        body = r.json()
        assert len(body["rows"]) >= 8
        assert {"pairs-trading"} & {row["slug"] for row in body["rows"]}
        d = client.get("/api/v1/leaderboard/donchian-breakout")
        assert d.status_code == 404  # nothing cached in a fresh dir

"""Leaderboard: canonical-run caching, FIFO paper P&L, ranking, API."""

from __future__ import annotations

import json
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
    monkeypatch.setattr(lb_config, "_SIDECAR_DIR", tmp_path / "uni")
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


def test_catalog_summarises_cached_runs(cache_dir, monkeypatch, db):
    monkeypatch.setattr(
        lb_service, "run_adhoc",
        lambda *a, **k: _fake_report(k["slug"], ret=42.0, sharpe=1.4, dd=12.0, trades=180),
    )
    run_canonical(None, None, "donchian-breakout")

    cat = lb_service.catalog(db)
    assert cat["meta"]["catalog_size"] >= 10
    assert cat["meta"]["catalog_ran"] >= 1
    assert cat["meta"]["total_backtests"] == cat["meta"]["catalog_ran"] + cat["meta"]["user_backtests"]

    done = next(e for e in cat["strategies"] if e["slug"] == "donchian-breakout")
    assert done["status"] == "ok"
    s = done["summary"]
    assert s["verdict"] in ("strong", "tradeable", "marginal", "avoid", "ruined", "insufficient")
    assert s["what_we_did"] and s["what_we_saw"] and s["what_to_look_at"]
    assert any("42.0%" in line for line in s["what_we_saw"])

    pending = next(e for e in cat["strategies"] if e["status"] == "not_run")
    assert pending["summary"] is None


# --- out-of-process refresh (refresh_runner / refresh_control) --------------

def test_refresh_runner_writes_progress_and_finishes(tmp_path, monkeypatch):
    import types

    import app.db.session as db_session
    import app.leaderboard.service as svc
    from app.leaderboard import refresh_runner as rr

    monkeypatch.setattr(db_session, "SessionLocal",
                        lambda: types.SimpleNamespace(close=lambda: None))

    def fake_run_canonical(db, settings, slug):
        if slug == "mean-reversion":
            raise RuntimeError("boom")
        return {"metrics": {"return_pct": 12.0, "sharpe_ratio": 0.3, "total_trades": 40},
                "ruined": False}

    monkeypatch.setattr(svc, "run_canonical", fake_run_canonical)
    sp = tmp_path / "status.json"
    final = rr.run(["donchian-breakout", "mean-reversion", "not-a-real-slug"], status_path=sp)

    assert final["state"] == "done"
    assert final["completed"] == 3 and final["total"] == 3
    assert final["results"]["donchian-breakout"].startswith("ok:")
    assert final["results"]["mean-reversion"].startswith("error: boom")
    assert "skipped" in final["results"]["not-a-real-slug"]
    on_disk = json.loads(sp.read_text())
    assert on_disk["state"] == "done" and on_disk["current"] is None


def test_refresh_control_start_status_and_conflict(tmp_path, monkeypatch):
    import os

    from app.core.exceptions import ConflictError
    from app.leaderboard import refresh_control as rc

    monkeypatch.setattr(rc, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(rc, "_LOG_PATH", tmp_path / "refresh.log")

    class _FakeProc:
        pid = 999_999_999          # not a real live process

    monkeypatch.setattr(rc.subprocess, "Popen", lambda *a, **k: _FakeProc())
    out = rc.start_refresh(["donchian-breakout"])
    assert out["job"] == "started" and out["pid"] == 999_999_999

    # pid isn't alive -> status reconciles running -> stalled, and a new start is allowed
    st = rc.read_status()
    assert st["state"] == "stalled"

    # now simulate a genuinely running job (our own pid) -> conflict
    (tmp_path / "status.json").write_text(json.dumps(
        {"state": "running", "pid": os.getpid(), "completed": 2, "total": 10}))
    assert rc.is_running() is True
    with pytest.raises(ConflictError):
        rc.start_refresh(None)


def test_refresh_endpoint_is_202_and_status_readable(cache_dir, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.v1.leaderboard as lb_api
    from app.main import app

    started = {}
    monkeypatch.setattr(lb_api, "start_refresh",
                        lambda slugs=None: started.update(slugs=slugs) or {"job": "started", "pid": 1,
                                                                           "slugs": slugs or "all",
                                                                           "status_url": "x"})
    monkeypatch.setattr(lb_api, "read_status", lambda: {"state": "running", "completed": 3, "total": 24})

    with TestClient(app) as client:
        r = client.post("/api/v1/leaderboard/refresh", json={"slugs": None})
        assert r.status_code == 202 and r.json()["job"] == "started"
        s = client.get("/api/v1/leaderboard/refresh/status")
        assert s.status_code == 200 and s.json()["state"] == "running"
        one = client.post("/api/v1/leaderboard/refresh/donchian-breakout")
        assert one.status_code == 202 and started["slugs"] == ["donchian-breakout"]
        bad = client.post("/api/v1/leaderboard/refresh/nope")
        assert bad.status_code == 404

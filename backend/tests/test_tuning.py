"""Preset tuning: combo grid, IS/OOS split scoring, verdict, adoption."""

from __future__ import annotations

import pytest

from app.backtesting.adhoc import AdhocReport
from app.tuning import adopted as adopted_mod
from app.tuning import service as tune_service
from app.tuning import store as tune_store
from app.tuning.service import _combo_grid, _split_metrics, run_tuning, tuning_for


@pytest.fixture()
def caches(tmp_path, monkeypatch):
    monkeypatch.setattr(tune_store, "_DIR", tmp_path / "tune")
    monkeypatch.setattr(adopted_mod, "_RUNTIME", tmp_path / "tune" / "adopted.json")
    yield


def test_combo_grid_includes_the_preset_value():
    grid = {"lookback": [15, 20, 30], "entry_zscore": [1.5, 2.5]}
    combos = _combo_grid(grid, {"lookback": 40, "entry_zscore": 2.5})
    # preset lookback=40 was appended, so 4 x 2 = 8 combos, and 40 is present
    assert len(combos) == 8
    assert any(c["lookback"] == 40 for c in combos)


def test_split_metrics_halves_the_curve():
    curve = [[f"2024-01-{i + 1:02d}T00:00:00+05:30", 100_000 + i * 100] for i in range(30)]
    is_m, oos_m, split_day = _split_metrics(curve, 0.6)
    assert is_m and oos_m
    assert split_day.startswith("2024-01")


def _report(slug: str, *, is_sh: float, oos_sh: float, oos_trades: int) -> AdhocReport:
    """Curve of ~250 daily points whose computed Sharpe on the first 60% is
    ~``is_sh`` and on the last 40% is ~``oos_sh`` (Gaussian returns with
    mu/sigma tuned to the target)."""
    import datetime as _dt
    import random

    rng = random.Random(abs(hash((slug, is_sh, oos_sh))) & 0xFFFF)
    sigma = 0.01

    def _half(target: float, n: int) -> list[float]:
        mu = target * sigma / (252 ** 0.5)
        return [rng.gauss(mu, sigma) for _ in range(n)]

    rets = _half(is_sh, 150) + _half(oos_sh, 100)
    v = 100_000.0
    d0 = _dt.date(2021, 1, 1)
    curve = [[d0.isoformat() + "T00:00:00+05:30", v]]
    for i, r in enumerate(rets):
        v *= 1 + r
        curve.append([(d0 + _dt.timedelta(days=i + 1)).isoformat() + "T00:00:00+05:30", round(v, 2)])
    # OOS window starts around index 150 -> ~2021-06
    trades = [{"exit_time": "2021-09-15T00:00:00+05:30", "net_pnl": 100.0} for _ in range(oos_trades)]
    return AdhocReport(
        slug=slug, strategy_name=slug, preset="balanced", timeframe="1d",
        start="2021-01-01", end="2024-01-01", capital=1_000_000.0,
        requested_symbols=[], used_symbols=["AAA"], skipped=[], parameters={},
        metrics={"total_trades": oos_trades + 10, "diagnostics": {"ruined": False}},
        charts={}, equity_curve=curve, per_symbol=[], trades=trades,
        data_quality={"ok": True, "warnings": []}, caveats=[], generated_at="2024-01-01T00:00:00",
        trade_pnls=[100.0] * (oos_trades + 10),
    )


def test_run_tuning_recommends_a_robust_improvement(caches, monkeypatch, db):
    # preset (lookback=20) is mediocre both halves; lookback=30 is good on BOTH.
    def _fake(_db, _s, *, slug, overrides, **k):
        lb = overrides.get("lookback")
        if lb == 30:
            return _report(slug, is_sh=6.0, oos_sh=5.0, oos_trades=40)
        if lb == 15:
            return _report(slug, is_sh=8.0, oos_sh=-1.0, oos_trades=40)  # IS-only spike
        return _report(slug, is_sh=1.0, oos_sh=0.8, oos_trades=40)

    monkeypatch.setattr(tune_service, "run_adhoc", _fake)
    p = run_tuning(db, None, "mean-reversion")
    assert p["verdict"] == "recommend_tuned"
    assert p["recommended_overrides"]["lookback"] == 30
    # the IS-only spike (lb=15) must NOT win
    assert p["recommended_overrides"]["lookback"] != 15
    assert tuning_for("mean-reversion")["verdict"] == "recommend_tuned"


def test_run_tuning_keeps_preset_when_nothing_beats_it(caches, monkeypatch, db):
    monkeypatch.setattr(
        tune_service, "run_adhoc",
        lambda *a, **k: _report(k["slug"], is_sh=1.2, oos_sh=1.0, oos_trades=30),
    )
    p = run_tuning(db, None, "donchian-breakout")
    assert p["verdict"] == "keep_preset"
    assert p["recommended_overrides"] is None


def test_run_tuning_no_eligible_when_too_few_oos_trades(caches, monkeypatch, db):
    monkeypatch.setattr(
        tune_service, "run_adhoc",
        lambda *a, **k: _report(k["slug"], is_sh=3.0, oos_sh=3.0, oos_trades=1),
    )
    p = run_tuning(db, None, "donchian-breakout")
    assert p["verdict"] == "no_eligible_combo"


def test_adopt_roundtrip(caches):
    from app.tuning import set_runtime_adoption, tuned_overrides

    assert tuned_overrides("mean-reversion") == {}
    set_runtime_adoption("mean-reversion", {"lookback": 30})
    assert tuned_overrides("mean-reversion") == {"lookback": 30}
    set_runtime_adoption("mean-reversion", None)
    assert tuned_overrides("mean-reversion") == {}

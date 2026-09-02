"""Chinese Transformer — features, targets, splits, baseline rankers, the
research pipeline, leakage defenses and the deployable template."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.chinese_transformer.data_quality import DataQualityEngine, Severity
from app.chinese_transformer.evaluation import evaluate
from app.chinese_transformer.features import FEATURE_NAMES, FeaturePipeline, raw_features
from app.chinese_transformer.models import (
    CrossSectionalScaler,
    GradientBoostedRanker,
    RidgeRanker,
)
from app.chinese_transformer.pipeline import ResearchConfig, ResearchPipeline
from app.chinese_transformer.splits import walk_forward
from app.chinese_transformer.targets import build_targets
from app.chinese_transformer.universe import UniverseConfig, UniverseManager
from app.strategies.base import Bar

IST = "+05:30"


def _bars(sym: str, closes: list[float], *, start: date = date(2022, 1, 3),
          vol: float = 1e6) -> list[Bar]:
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ts = f"{d.isoformat()}T09:15:00{IST}"
        out.append(Bar(timestamp=ts, open=c * 0.999, high=c * 1.01, low=c * 0.99,
                       close=c, volume=vol, instrument=sym))
        d += timedelta(days=1)
    return out


def _gbm(n: int, seed: int, drift: float = 0.0003, sigma: float = 0.015,
         s0: float = 100.0) -> list[float]:
    rng = random.Random(seed)
    p, out = s0, []
    for _ in range(n):
        p *= math.exp(drift + sigma * rng.gauss(0, 1))
        out.append(round(p, 2))
    return out


def _universe_bars(n_sym: int, n_bars: int, seed: int = 0) -> dict[str, list[Bar]]:
    return {f"SYM{i:02d}": _bars(f"SYM{i:02d}", _gbm(n_bars, seed + i)) for i in range(n_sym)}


# --- data quality -------------------------------------------------

def test_data_quality_flags_extreme_move_and_bad_ohlc():
    good = _gbm(120, 1)
    good[60] = good[59] * 1.8  # +80% one-day jump -> extreme_return ERROR
    bars = _bars("AAA", good)
    bars[80] = Bar(timestamp=bars[80].timestamp, open=10, high=5, low=8, close=9,
                   volume=1e6, instrument="AAA")  # high < open -> invalid_ohlc CRITICAL
    rep = DataQualityEngine().check_symbol("AAA", bars)
    codes = {i.code for i in rep.issues}
    assert "extreme_return" in codes
    assert "invalid_ohlc" in codes
    assert rep.worst is Severity.CRITICAL
    assert not rep.tradeable


def test_data_quality_report_excludes_blocking_symbols():
    ok = _bars("OK", _gbm(400, 2))
    short = _bars("SHORT", _gbm(20, 3))
    rep = DataQualityEngine().report({"OK": ok, "SHORT": short})
    assert "OK" in rep.tradeable_symbols()
    assert "SHORT" not in rep.tradeable_symbols()
    assert "SHORT" in rep.excluded()


# --- features ---------------------------------------------------

def test_raw_features_complete_and_finite():
    c = np.array(_gbm(300, 4))
    f = raw_features(c, c * 1.01, c * 0.99, np.full(300, 1e6))
    assert set(f) >= {"ret_20", "vol_60", "rsi_14", "adx_14", "amihud_20"}
    assert all(math.isfinite(v) for v in f.values())


def test_feature_panel_is_causal():
    """A row's features must not change when future bars are appended."""
    bars = _universe_bars(12, 320, seed=10)
    fp = FeaturePipeline()
    dates = sorted({_d(b) for b in bars["SYM00"]})
    rcal = dates[200:210]
    sect = dict.fromkeys(bars, "X")
    full = fp.panel(bars, rebalance_dates=rcal, sector_by_symbol=sect, min_symbols=5)
    truncated = {s: b[:260] for s, b in bars.items()}
    part = fp.panel(truncated, rebalance_dates=rcal, sector_by_symbol=sect, min_symbols=5)
    common = full.index.intersection(part.index)
    assert len(common) > 20
    a = full.loc[common, FEATURE_NAMES].to_numpy()
    b = part.loc[common, FEATURE_NAMES].to_numpy()
    assert np.allclose(a, b, atol=1e-9)


def _d(b):
    from app.chinese_transformer.data_quality import _ts_to_date

    return _ts_to_date(b.timestamp)


# --- targets --------------------------------------------------

def test_targets_use_only_future_bars_and_purge_the_tail():
    bars = _universe_bars(10, 200, seed=20)
    dates = sorted({_d(b) for b in bars["SYM00"]})
    rcal = dates[100:180]
    tgt = build_targets(bars, rebalance_dates=rcal, horizon=20, kind="rank")
    labelled = sorted({d.date() for d, _s in tgt.index})
    # nothing within `horizon` bars of the very last date can be labelled
    assert max(labelled) <= dates[-21]
    assert tgt["target"].between(0.0, 1.0).all()


# --- splits -------------------------------------------------

def test_walk_forward_embargo_prevents_overlap():
    idx = pd.MultiIndex.from_product(
        [pd.date_range("2021-01-01", periods=260, freq="B"), ["A", "B"]],
        names=["date", "symbol"],
    )
    folds = walk_forward(idx, horizon=4, n_folds=3, scheme="expanding", min_train=120)
    assert folds
    for f in folds:
        assert f.train_end < f.test_start
        gap = (f.test_start - f.train_end).days
        assert gap >= 4  # embargo respected


# --- baseline rankers ----------------------------------------

def test_rankers_recover_a_planted_signal():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(1500, 12))
    y = 0.8 * x[:, 0] - 0.4 * x[:, 3] + 0.1 * rng.normal(size=1500)
    xtr, ytr, xte, yte = x[:1100], y[:1100], x[1100:], y[1100:]
    sc = CrossSectionalScaler().fit(xtr)
    for model in (RidgeRanker(), GradientBoostedRanker(n_estimators=80, seed=1)):
        model.fit(sc.transform(xtr), ytr)
        pred = model.predict(sc.transform(xte))
        rho = _spearman(pred, yte)
        assert rho > 0.6, f"{type(model).__name__} rho={rho:.3f}"


def _spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    return float((ra * rb).sum() / math.sqrt((ra**2).sum() * (rb**2).sum()))


# --- pipeline + leakage ---------------------------------------

def test_pipeline_runs_end_to_end_and_passes_leakage_checks():
    bars = _universe_bars(24, 460, seed=30)
    cfg = ResearchConfig(rebalance_frequency="weekly", horizon_days=15, ranker="ridge",
                         n_folds=3, min_train_dates=40)
    res = ResearchPipeline(cfg).run(bars, expected_bars=460)
    d = res.as_dict()
    assert d["panel_rows"] > 200
    assert d["leakage_checks"]["passed"] is True
    assert d["leakage_checks"]["max_feature_target_corr"] < 0.6
    assert "rank_ic_mean" in d["pooled"]
    assert d["folds"], "expected at least one walk-forward fold"


def test_leakage_probe_catches_a_planted_future_feature():
    """If a feature literally equals the forward return, the check must fail."""
    bars = _universe_bars(18, 360, seed=40)
    fp = FeaturePipeline()
    dates = sorted({_d(b) for b in bars["SYM00"]})
    rcal = dates[120:300:3]
    sect = dict.fromkeys(bars, "X")
    panel = fp.panel(bars, rebalance_dates=rcal, sector_by_symbol=sect, min_symbols=8)
    tgt = build_targets(bars, rebalance_dates=rcal, horizon=15, kind="rank")
    joined = panel.join(tgt, how="inner").dropna(subset=["target"])
    joined["ret_20"] = joined["fwd_return"]  # plant the leak
    checks = ResearchPipeline()._leakage_checks(joined, FEATURE_NAMES, 15)
    assert checks["feature_target_corr_ok"] is False
    assert checks["passed"] is False


# --- evaluation --------------------------------------------

def test_evaluate_reports_positive_ic_when_score_predicts_forward_return():
    rows = []
    rng = np.random.default_rng(2)
    for k in range(30):
        d = pd.Timestamp("2023-01-02") + pd.Timedelta(days=7 * k)
        for i in range(25):
            score = rng.normal()
            fwd = 0.02 * score + 0.01 * rng.normal()
            rows.append({"date": d, "symbol": f"S{i}", "score": score, "fwd_return": fwd})
    df = pd.DataFrame(rows).set_index(["date", "symbol"])
    out = evaluate(df, quantiles=5, top_k=5)
    assert out["rank_ic_mean"] > 0.3
    assert out["long_short_spread"] > 0


# --- universe ---------------------------------------------

def test_universe_screen_drops_illiquid_and_short_history():
    um = UniverseManager(UniverseConfig(name="NIFTY_50", min_history_bars=250,
                                        min_avg_daily_value=1e9, min_price=10.0))
    liquid = _bars("HDFCBANK", _gbm(300, 5), vol=5e5)      # 5e5 * ~100 = 5e7 < 1e9 -> dropped
    res = um.screen(date(2023, 6, 1), bars_by_symbol={"HDFCBANK": liquid})
    assert "HDFCBANK" in res.dropped


# --- deployable template --------------------------------

def test_template_runs_through_backtest_engine_and_trades():
    from app.backtesting.costs import CostConfig, CostModel
    from app.backtesting.engine import BacktestEngine
    from app.strategies.library.chinese_transformer import ChineseTransformerStrategy

    # 20 names, 400 daily bars, a spread of drifts so the ranking has structure
    bars = {
        f"N{i:02d}": _bars(f"N{i:02d}", _gbm(400, 100 + i, drift=0.0002 + 0.0002 * (i % 5)))
        for i in range(20)
    }
    params = ChineseTransformerStrategy.resolve_params({
        **ChineseTransformerStrategy.PRESETS["balanced"],
        "min_history_bars": 200, "min_avg_daily_value": 0.0, "num_positions": 5,
        "regime_exposure_scaling": False, "capital_allocation": 1_000_000.0,
    })
    res = BacktestEngine(
        ChineseTransformerStrategy, params, initial_capital=1_000_000.0,
        cost_model=CostModel(CostConfig()),
    ).run(bars)
    assert res.diagnostics.total_bars > 5000
    assert len(res.fills) > 0
    assert len(res.final_positions) > 0

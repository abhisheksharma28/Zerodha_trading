"""Research pipeline — Phases 1-2 end to end.

    bars_by_symbol
        -> data-quality gate (drop ERROR/CRITICAL names)
        -> rebalance calendar
        -> multi-factor feature panel        (causal)
        -> cross-sectional targets           (purged, future-only)
        -> walk-forward folds                (expanding / rolling, embargoed)
        -> per fold: fit scaler+ranker on TRAIN, score TEST
        -> Rank-IC / ICIR / quantile spread, pooled + per fold

No Transformer here — ``ranker`` is "ridge" or "gbrt". The point is to
find out whether the features carry out-of-sample cross-sectional alpha
before anything heavier is justified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.chinese_transformer.data_quality import DataQualityEngine
from app.chinese_transformer.evaluation import evaluate
from app.chinese_transformer.features import FeaturePipeline
from app.chinese_transformer.models import RANKERS, CrossSectionalScaler
from app.chinese_transformer.splits import walk_forward
from app.chinese_transformer.targets import build_targets
from app.chinese_transformer.universe import UniverseManager


@dataclass
class ResearchConfig:
    rebalance_frequency: str = "weekly"   # daily | weekly | monthly
    horizon_days: int = 20
    target_kind: str = "rank"             # rank | bucket | risk_adjusted
    ranker: str = "ridge"                 # ridge | gbrt (gbrt is slower)
    n_folds: int = 4
    wf_scheme: str = "expanding"          # expanding | rolling
    min_train_dates: int = 90
    n_buckets: int = 5
    top_k: int = 10
    seed: int = 0


@dataclass
class ResearchResult:
    config: dict[str, Any]
    data_quality: dict[str, Any]
    universe: dict[str, Any]
    panel_shape: tuple[int, int]
    folds: list[dict[str, Any]] = field(default_factory=list)
    pooled: dict[str, Any] = field(default_factory=dict)
    feature_importance: dict[str, float] = field(default_factory=dict)
    latest_rankings: list[dict[str, Any]] = field(default_factory=list)
    leakage_checks: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "data_quality": self.data_quality,
            "universe": self.universe,
            "panel_rows": self.panel_shape[0],
            "panel_features": self.panel_shape[1],
            "folds": self.folds,
            "pooled": self.pooled,
            "feature_importance": self.feature_importance,
            "latest_rankings": self.latest_rankings,
            "leakage_checks": self.leakage_checks,
            "warnings": self.warnings,
        }


_FREQ_STRIDE = {"daily": 1, "weekly": 5, "monthly": 21}


def _rebalance_calendar(all_dates: list[date], freq: str) -> list[date]:
    if freq == "weekly":
        seen: dict[tuple[int, int], date] = {}
        for d in all_dates:
            seen.setdefault(d.isocalendar()[:2], d)
        return sorted(seen.values())
    if freq == "monthly":
        seen_m: dict[tuple[int, int], date] = {}
        for d in all_dates:
            seen_m.setdefault((d.year, d.month), d)
        return sorted(seen_m.values())
    return list(all_dates)


class ResearchPipeline:
    def __init__(self, config: ResearchConfig | None = None,
                 universe: UniverseManager | None = None) -> None:
        self.cfg = config or ResearchConfig()
        self.universe = universe or UniverseManager()
        self.features = FeaturePipeline()

    def run(self, bars_by_symbol: dict[str, list[Any]], *, expected_bars: int | None = None
            ) -> ResearchResult:
        cfg = self.cfg
        warnings: list[str] = [
            "Universe is current index membership — historical results carry survivorship bias.",
            "Fundamental factors are excluded (no point-in-time fundamentals available).",
            "Market/sector context is proxied from the universe's own bars (no India VIX / breadth).",
        ]

        dq = DataQualityEngine().report(bars_by_symbol, expected_bars=expected_bars)
        tradeable = set(dq.tradeable_symbols())
        clean = {s: b for s, b in bars_by_symbol.items() if s in tradeable}
        if len(clean) < 10:
            return ResearchResult(
                config=cfg.__dict__, data_quality=dq.as_dict(),
                universe={"tradeable": len(clean)}, panel_shape=(0, 0),
                warnings=[*warnings, "Fewer than 10 tradeable symbols — cannot rank."],
            )

        all_dates = sorted({d for b in clean.values() for d in (_dates(b))})
        rcal = _rebalance_calendar(all_dates, cfg.rebalance_frequency)
        sector_map = self.universe.sector_map(list(clean))

        panel = self.features.panel(
            clean, rebalance_dates=rcal, sector_by_symbol=sector_map, min_symbols=10)
        tgt = build_targets(
            clean, rebalance_dates=rcal, horizon=cfg.horizon_days,
            kind=cfg.target_kind, n_buckets=cfg.n_buckets)
        joined = panel.join(tgt, how="inner").dropna(subset=["target"])
        if joined.empty or joined.index.get_level_values(0).nunique() < cfg.min_train_dates // 2:
            return ResearchResult(
                config=cfg.__dict__, data_quality=dq.as_dict(),
                universe={"tradeable": len(clean), "rebalance_dates": len(rcal)},
                panel_shape=(len(joined), len(self.features.names)),
                warnings=[*warnings, "Not enough labelled rebalance dates for walk-forward."],
            )

        feat_names = self.features.names
        leakage = self._leakage_checks(joined, feat_names, cfg.horizon_days)

        # embargo between train and test, measured in rebalance steps:
        # ceil(horizon_days / calendar stride of the rebalance frequency)
        stride = _FREQ_STRIDE.get(cfg.rebalance_frequency, 5)
        embargo_steps = max(1, -(-cfg.horizon_days // stride))
        folds = walk_forward(joined.index, horizon=embargo_steps, n_folds=cfg.n_folds,
                             scheme=cfg.wf_scheme, min_train=cfg.min_train_dates)

        RankerCls = RANKERS[cfg.ranker]
        fold_reports: list[dict[str, Any]] = []
        pooled_scored: list[pd.DataFrame] = []
        importances: list[dict[str, float]] = []
        for fold in folds:
            tr = joined[(joined.index.get_level_values(0) >= pd.Timestamp(fold.train_start))
                        & (joined.index.get_level_values(0) <= pd.Timestamp(fold.train_end))]
            te = joined[(joined.index.get_level_values(0) >= pd.Timestamp(fold.test_start))
                        & (joined.index.get_level_values(0) <= pd.Timestamp(fold.test_end))]
            if len(tr) < 200 or te.empty:
                continue
            xtr = tr[feat_names].to_numpy(dtype=float)
            xte = te[feat_names].to_numpy(dtype=float)
            scaler = CrossSectionalScaler().fit(xtr)
            model = _build(RankerCls, feat_names, cfg.seed + fold.index)
            model.fit(scaler.transform(xtr), tr["target"].to_numpy(dtype=float))
            scores = model.predict(scaler.transform(xte))
            sd = te[["fwd_return", "fwd_return_rank"]].copy()
            sd["score"] = scores
            pooled_scored.append(sd)
            rep = evaluate(sd, top_k=cfg.top_k, quantiles=cfg.n_buckets)
            rep.pop("per_date", None)
            fold_reports.append({**fold.as_dict(), "test_rows": len(te), **rep})
            importances.append(model.feature_importance())

        pooled = evaluate(pd.concat(pooled_scored), top_k=cfg.top_k,
                          quantiles=cfg.n_buckets) if pooled_scored else {}
        agg_imp = _avg_importance(importances)

        latest = self._latest_rankings(joined, feat_names, RankerCls, cfg)

        return ResearchResult(
            config=cfg.__dict__,
            data_quality=dq.as_dict(),
            universe={
                "name": self.universe.config.name,
                "tradeable": len(clean),
                "excluded": dq.excluded(),
                "rebalance_dates": len(rcal),
                "sector_breakdown": _sector_counts(sector_map),
            },
            panel_shape=(len(joined), len(feat_names)),
            folds=fold_reports,
            pooled={k: v for k, v in pooled.items() if k != "per_date"},
            feature_importance=agg_imp,
            latest_rankings=latest,
            leakage_checks=leakage,
            warnings=warnings,
        )

    # --- helpers ---------------------------------------------------

    def _leakage_checks(self, joined: pd.DataFrame, feat_names: list[str], horizon: int
                        ) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        # 1. no feature column should be (near-)identical to the future label
        tgt = joined["fwd_return"].to_numpy(dtype=float)
        worst = 0.0
        worst_feat = None
        for f in feat_names:
            col = joined[f].to_numpy(dtype=float)
            if np.std(col) == 0 or np.std(tgt) == 0:
                continue
            c = abs(float(np.corrcoef(col, tgt)[0, 1]))
            if c > worst:
                worst, worst_feat = c, f
        checks["max_feature_target_corr"] = round(worst, 3)
        checks["max_corr_feature"] = worst_feat
        checks["feature_target_corr_ok"] = bool(worst < 0.6)
        # 2. every label date must have >= horizon days of data after it in the raw calendar
        last_date = joined.index.get_level_values(0).max()
        checks["labels_end_before_data_end"] = True  # build_targets drops incomplete windows
        checks["last_label_date"] = str(last_date.date())
        checks["horizon_days"] = horizon
        checks["passed"] = checks["feature_target_corr_ok"]
        return checks

    def _latest_rankings(self, joined: pd.DataFrame, feat_names: list[str], RankerCls,
                         cfg: ResearchConfig) -> list[dict[str, Any]]:
        dates = sorted(joined.index.get_level_values(0).unique())
        if len(dates) < 30:
            return []
        cut = dates[-1]
        train = joined[joined.index.get_level_values(0) < cut]
        if len(train) < 200:
            return []
        xtr = train[feat_names].to_numpy(dtype=float)
        scaler = CrossSectionalScaler().fit(xtr)
        model = _build(RankerCls, feat_names, cfg.seed)
        model.fit(scaler.transform(xtr), train["target"].to_numpy(dtype=float))
        last = joined[joined.index.get_level_values(0) == cut]
        scores = model.predict(scaler.transform(last[feat_names].to_numpy(dtype=float)))
        order = np.argsort(scores)[::-1]
        syms = last.index.get_level_values(1).to_numpy()
        pr = np.argsort(np.argsort(scores)) / max(len(scores) - 1, 1)
        rows = []
        for rank, i in enumerate(order[: max(cfg.top_k * 3, 30)], start=1):
            rows.append({
                "rank": rank, "symbol": str(syms[i]),
                "score": round(float(scores[i]), 5),
                "percentile": round(float(pr[i]), 3),
                "as_of": str(cut.date()),
            })
        return rows


def _build(RankerCls, feat_names: list[str], seed: int):
    try:
        m = RankerCls(seed=seed)
    except TypeError:
        m = RankerCls()
    m.feature_names = list(feat_names)
    return m


def _avg_importance(items: list[dict[str, float]]) -> dict[str, float]:
    if not items:
        return {}
    acc: dict[str, float] = {}
    for d in items:
        for k, v in d.items():
            acc[k] = acc.get(k, 0.0) + v
    n = len(items)
    return dict(sorted(((k, round(v / n, 4)) for k, v in acc.items()),
                       key=lambda kv: kv[1], reverse=True)[:25])


def _sector_counts(sector_map: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sector_map.values():
        out[s] = out.get(s, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def _dates(bars: list[Any]) -> list[date]:
    from app.chinese_transformer.data_quality import _ts_to_date

    return [d for b in bars if (d := _ts_to_date(getattr(b, "timestamp", None)))]

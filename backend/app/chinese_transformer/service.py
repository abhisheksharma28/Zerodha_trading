"""Chinese Transformer orchestration — status, feature catalog, research run."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.adhoc import fetch_candles
from app.chinese_transformer import store
from app.chinese_transformer.features import FeaturePipeline
from app.chinese_transformer.pipeline import ResearchConfig, ResearchPipeline
from app.chinese_transformer.universe import UniverseConfig, UniverseManager
from app.config import Settings
from app.core.exceptions import ValidationError
from app.strategies.library import get_template

_SLUG = "chinese-transformer"

_LIMITATIONS = [
    "Survivorship bias: the universe is today's index membership; NSE point-in-time "
    "membership / delisting dates are not available to this platform, so historical "
    "runs over-represent survivors (disclosed, not eliminated).",
    "No point-in-time fundamentals: the fundamentals providers here return current "
    "snapshots, so fundamental factors are live/paper only and excluded from the "
    "historical feature panel.",
    "No India VIX / market breadth / delivery-% history: market and sector context "
    "features are proxied from the universe's own daily bars.",
    "~3-4 years of daily history from Kite: the shipped ranker is a ridge / gradient-"
    "boosted baseline. A Transformer is only justified once the baseline shows "
    "out-of-sample Rank-IC.",
    "Backtests are not live performance. No model is deployed to live automatically.",
]


def strategy_status() -> dict[str, Any]:
    tpl = get_template(_SLUG)
    return {
        "slug": _SLUG,
        "name": tpl.NAME,
        "category": tpl.CATEGORY,
        "philosophy": (
            "Cross-sectional alpha: rank the whole universe by expected relative "
            "risk-adjusted return and hold the strongest names. Not a price-direction model."
        ),
        "pipeline": {
            "phases_available": [
                "1: universe + data-quality + multi-factor features",
                "2: cross-sectional targets + walk-forward + baseline rankers + Rank-IC",
            ],
            "phases_pending": [
                "3: numerical Transformer (baseline-first decision — deferred)",
                "4-7: portfolio optimizer variants, standalone risk engine, dedicated backtest",
                "8-10: dashboard, paper, live execution",
            ],
        },
        "deployable_template": {
            "runs_through": "existing BacktestEngine / leaderboard / robustness stack",
            "scorer": "transparent standardized multi-factor composite (no trained model)",
            "presets": list(tpl.presets()),
        },
        "limitations": _LIMITATIONS,
    }


def feature_catalog() -> dict[str, Any]:
    specs = FeaturePipeline().spec_table()
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for s in specs:
        by_cat.setdefault(s["category"], []).append(s)
    return {
        "feature_count": len(specs),
        "categories": {k: len(v) for k, v in by_cat.items()},
        "features": by_cat,
        "excluded_categories": {
            "fundamental": "No point-in-time fundamentals available — would leak in a "
            "historical panel. Added live-only.",
            "alternative_data": "News / FII-DII / earnings-call sentiment — interface "
            "reserved, not wired.",
        },
    }


def run_research(
    db: Session,
    settings: Settings,
    *,
    universe: str = "NIFTY_100",
    lookback_days: int = 1400,
    rebalance_frequency: str = "weekly",
    horizon_days: int = 20,
    target_kind: str = "rank",
    ranker: str = "ridge",
    n_folds: int = 4,
    wf_scheme: str = "expanding",
) -> dict[str, Any]:
    if ranker not in ("ridge", "gbrt"):
        raise ValidationError("ranker must be 'ridge' or 'gbrt'")
    if target_kind not in ("rank", "bucket", "risk_adjusted"):
        raise ValidationError("target_kind must be 'rank', 'bucket' or 'risk_adjusted'")
    if rebalance_frequency not in ("daily", "weekly", "monthly"):
        raise ValidationError("rebalance_frequency must be 'daily', 'weekly' or 'monthly'")

    ucfg = UniverseConfig(name=universe)
    symbols = ucfg.base_symbols()
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=max(400, lookback_days))
    candles, skipped = fetch_candles(
        db, settings, symbols=symbols, timeframe="1d",
        start=from_dt.date().isoformat(), end=to_dt.date().isoformat(),
    )
    if len(candles) < 10:
        raise ValidationError(
            f"Need daily history for at least 10 names; got {len(candles)}. skipped={skipped[:5]}"
        )

    # ~250 trading days a year — expected bar count over the window
    expected = int((to_dt - from_dt).days * (5 / 7) * 0.96)
    cfg = ResearchConfig(
        rebalance_frequency=rebalance_frequency, horizon_days=horizon_days,
        target_kind=target_kind, ranker=ranker, n_folds=n_folds, wf_scheme=wf_scheme,
    )
    result = ResearchPipeline(cfg, UniverseManager(ucfg)).run(candles, expected_bars=expected)

    payload: dict[str, Any] = {
        "slug": _SLUG,
        "universe": universe,
        "requested_symbols": len(symbols),
        "fetched_symbols": len(candles),
        "skipped": skipped,
        "window": {"start": from_dt.date().isoformat(), "end": to_dt.date().isoformat()},
        **result.as_dict(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    key = f"{universe}__{rebalance_frequency}__{horizon_days}__{target_kind}__{ranker}"
    store.save("research", key, payload)
    return payload


def latest_research() -> dict[str, Any]:
    runs = store.list_kind("research")
    if not runs:
        return {"available": False, "note": "No research run cached yet. POST /research to build one."}
    latest = max(runs, key=lambda r: float(r.get("cached_at", 0) or 0))
    return {"available": True, **latest}

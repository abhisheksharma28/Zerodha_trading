"""Chinese Transformer API — cross-sectional AI stock selection for NSE.

``GET`` endpoints are cheap (static metadata or a cached research run).
``POST /research`` is slow: it fetches ~3-4 years of daily bars for the
whole universe, builds the feature panel and runs walk-forward-validated
baseline rankers. Trigger it deliberately.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.chinese_transformer.service import (
    feature_catalog,
    latest_research,
    run_research,
    strategy_status,
)
from app.config import Settings, get_settings
from app.core.deps import get_db

router = APIRouter(prefix="/chinese-transformer", tags=["chinese-transformer"])


@router.get("/status")
def get_status() -> dict[str, Any]:
    return strategy_status()


@router.get("/features")
def get_features() -> dict[str, Any]:
    return feature_catalog()


@router.get("/research/latest")
def get_latest_research() -> dict[str, Any]:
    return latest_research()


@router.get("/rankings")
def get_rankings() -> dict[str, Any]:
    latest = latest_research()
    if not latest.get("available"):
        return latest
    return {
        "available": True,
        "as_of": latest.get("window", {}).get("end"),
        "universe": latest.get("universe"),
        "config": latest.get("config"),
        "rankings": latest.get("latest_rankings", []),
        "caveat": "Baseline ranker output, refit on all data up to the last rebalance. "
        "Research signal, not a live order list.",
    }


@router.post("/research")
def post_research(
    universe: str = Body("NIFTY_100", embed=True),
    lookback_days: int = Body(1400, embed=True),
    rebalance_frequency: str = Body("weekly", embed=True),
    horizon_days: int = Body(20, embed=True),
    target_kind: str = Body("rank", embed=True),
    ranker: str = Body("ridge", embed=True),
    n_folds: int = Body(4, embed=True),
    wf_scheme: str = Body("expanding", embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return run_research(
        db, settings, universe=universe, lookback_days=lookback_days,
        rebalance_frequency=rebalance_frequency, horizon_days=horizon_days,
        target_kind=target_kind, ranker=ranker, n_folds=n_folds, wf_scheme=wf_scheme,
    )

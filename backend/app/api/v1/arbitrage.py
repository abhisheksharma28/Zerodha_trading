"""Arbitrage Lab API — a subsystem separate from the Quant Strategy
Leaderboard and the normal backtest engine.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.arbitrage import store
from app.arbitrage.registry import get_arb_strategy
from app.arbitrage.service import (
    arb_library,
    arb_portfolio,
    discover_pairs_for_universe,
    run_arb_backtest,
)
from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import NotFoundError

router = APIRouter(prefix="/arbitrage", tags=["arbitrage"])


class ArbBacktestRequest(BaseModel):
    slug: str
    symbol_a: str
    symbol_b: str
    timeframe: str = "1d"
    start: str | None = None
    end: str | None = None
    preset: str = "balanced"
    parameters: dict[str, Any] | None = None
    sync_mode: str = "REJECT_STALE_DATA"
    max_data_age_seconds: float = 300.0


class PairDiscoveryRequest(BaseModel):
    symbols: list[str] = Field(min_length=2, max_length=60)
    timeframe: str = "1d"
    days: int = Field(default=500, ge=60, le=2500)
    adf_threshold: float = -3.0
    top_n: int = Field(default=40, ge=1, le=200)


@router.get("/strategies")
def list_strategies() -> dict[str, Any]:
    return arb_library()


@router.get("/strategies/{slug}")
def get_strategy(slug: str) -> dict[str, Any]:
    try:
        return get_arb_strategy(slug).detail()
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc


@router.post("/backtest")
def backtest(
    payload: ArbBacktestRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return run_arb_backtest(
        db, settings, slug=payload.slug, symbol_a=payload.symbol_a, symbol_b=payload.symbol_b,
        timeframe=payload.timeframe, start=payload.start, end=payload.end, preset=payload.preset,
        overrides=payload.parameters, sync_mode=payload.sync_mode,
        max_data_age_seconds=payload.max_data_age_seconds,
    )


@router.get("/backtests")
def list_backtests() -> dict[str, Any]:
    runs = store.list_kind("backtest")
    return {"runs": [
        {"slug": r["slug"], "strategy_name": r["strategy_name"], "legs": r["legs"],
         "preset": r["preset"], "timeframe": r["timeframe"],
         "metrics": {k: r["metrics"].get(k) for k in
                     ("net_pnl", "sharpe_ratio", "return_on_capital_pct", "arbitrage_quality_score",
                      "edge_capture_rate", "executed_trades")},
         "generated_at": r.get("generated_at")}
        for r in runs
    ]}


@router.get("/backtest/{slug}/{symbol_a}/{symbol_b}")
def get_backtest(slug: str, symbol_a: str, symbol_b: str) -> dict[str, Any]:
    blob = store.load("backtest", f"{slug}__{symbol_a}__{symbol_b}")
    if blob is None:
        raise NotFoundError("No cached arbitrage backtest for that strategy/pair.")
    return blob


@router.post("/pair-discovery")
def pair_discovery(
    payload: PairDiscoveryRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return discover_pairs_for_universe(
        db, settings, symbols=payload.symbols, timeframe=payload.timeframe, days=payload.days,
        adf_threshold=payload.adf_threshold, top_n=payload.top_n,
    )


@router.get("/pair-discovery/latest")
def latest_discovery() -> dict[str, Any]:
    runs = store.list_kind("discovery")
    if not runs:
        return {"available": False, "pairs": []}
    latest: dict[str, Any] = max(runs, key=lambda r: float(r.get("cached_at", 0) or 0))
    return {"available": True, **latest}


@router.get("/portfolio")
def portfolio() -> dict[str, Any]:
    return arb_portfolio()


@router.get("/scanner")
def scanner(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Phase-1 placeholder: the live opportunity scanner needs a real-time
    multi-instrument quote feed. Until that is wired it returns the shape
    with an explicit not-available flag rather than fake opportunities."""
    return {
        "available": False,
        "reason": "Live scanner needs a synchronised real-time quote feed for every leg — "
        "wired in a later phase. Use Pair Discovery + Backtest for now.",
        "opportunities": [],
        "statuses": ["WATCHING", "CANDIDATE", "EXECUTABLE", "EXECUTED", "EXPIRED", "REJECTED"],
    }


@router.post("/paper/{action}")
def paper_control(action: str, _body: dict | None = Body(default=None)) -> dict[str, Any]:
    """Phase-1 placeholder for the dedicated arbitrage paper-trading engine."""
    return {
        "available": False,
        "action": action,
        "reason": "The dedicated multi-leg arbitrage paper-trading engine (independent per-leg "
        "fills, hedge-state tracking, execution-quality scoring) is a later phase.",
    }

"""Sector Seasonality API — the research-grade engine.

  GET  /seasonality                 the pre-built report (audit, grid,
                                    per-month rankings, FDR verdict, backtests)
  GET  /seasonality/status          refresh status
  POST /seasonality/refresh         rebuild the report out of process (~1 min)
  GET  /seasonality/backtest        one walk-forward strategy, computed live
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.seasonality.backtest import STRATEGIES, walk_forward
from app.seasonality.store import load, read_status, start_refresh

router = APIRouter(prefix="/seasonality", tags=["seasonality"])


@router.get("")
def get_report() -> dict[str, Any]:
    report = load()
    if report is None:
        return {
            "available": False,
            "reason": "The seasonality report has not been built yet. "
            "POST /seasonality/refresh to build it (~1 minute).",
        }
    report["available"] = True
    return report


@router.get("/status")
def get_status() -> dict[str, Any]:
    return read_status()


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh() -> dict[str, Any]:
    try:
        return start_refresh()
    except RuntimeError as exc:
        return {"error": str(exc), "status": read_status()}


@router.get("/backtest")
def backtest(
    strategy: str = Query("E_long_top3_short_bottom3"),
    mode: str = Query("expanding", pattern="^(expanding|rolling)$"),
    start_test_year: int = Query(2012, ge=2005, le=2022),
    long_cost_bps: float = Query(30.0, ge=0.0, le=200.0),
    short_cost_bps: float = Query(60.0, ge=0.0, le=400.0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        return {"error": f"unknown strategy; choose one of {list(STRATEGIES)}"}
    return walk_forward(
        db, settings, strategy=strategy, mode=mode, start_test_year=start_test_year,
        long_cost_bps=long_cost_bps, short_cost_bps=short_cost_bps,
    ).to_dict()

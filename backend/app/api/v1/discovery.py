"""Portfolio Alpha Discovery Engine API.

Phase 1: the multi-asset universe + its ingested data coverage, and an
aligned return matrix for a chosen set of instruments (USD or INR).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.discovery import normalize, screen as screen_mod
from app.discovery import service

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/universe")
def universe(db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.universe_status(db)


@router.post("/returns")
def returns(
    payload: dict[str, Any] = Body(...),
    currency: str = Query("USD"),
    kind: str = Query("simple", pattern="^(simple|log)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aligned return matrix for ``payload['symbols']`` on their common
    history, in the requested currency (FX-adjusted for non-USD)."""
    symbols = [str(s).strip().upper() for s in (payload.get("symbols") or []) if s]
    if not symbols:
        return {"dates": [], "returns": {}, "prices": {}, "missing": ["<no symbols>"]}
    return normalize.returns_frame(db, symbols, currency=currency, kind=kind)


@router.get("/screen")
def screen(
    currency: str = Query("USD"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-instrument return / risk / consistency metrics + a composite
    screen_score and correlation cluster, over the ingested Tier A/B set."""
    return screen_mod.screen(db, currency=currency)


@router.get("/candidates")
def candidates(
    k: int = Query(12, ge=3, le=40),
    per_cluster: int = Query(1, ge=1, le=4),
    currency: str = Query("USD"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A low-correlation candidate set for the portfolio search."""
    return screen_mod.candidates(db, k=k, per_cluster=per_cluster, currency=currency)


@router.post("/optimize")
def optimize(
    payload: dict[str, Any] = Body(...),
    method: str = Query("max_sharpe"),
    constraint_mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive|unrestricted)$"),
    currency: str = Query("USD"),
    cost_bps: float = Query(10.0, ge=0.0, le=200.0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Optimize weights for ``payload['symbols']`` by ``method`` and
    evaluate the portfolio (metrics + IS/OOS + regime breakdown)."""
    symbols = [str(s) for s in (payload.get("symbols") or []) if s]
    if len(symbols) < 3:
        return {"available": False, "reason": "provide >= 3 symbols"}
    return service.optimize_and_evaluate(
        db, symbols=symbols, method=method, constraint_mode=constraint_mode,
        currency=currency, cost_bps=cost_bps,
    )

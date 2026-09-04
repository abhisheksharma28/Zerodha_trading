"""Portfolio Alpha Discovery Engine API.

Phase 1: the multi-asset universe + its ingested data coverage, and an
aligned return matrix for a chosen set of instruments (USD or INR).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.discovery import normalize, service

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

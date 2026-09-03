"""Market Scanner API - the recommendation feed on the Scanner tab.

  GET  /market-scanner/recommendations     live setups + expired-today + summary
  GET  /market-scanner/recommendations/{id}
  GET  /market-scanner/logbook             full resolved history + win/expectancy stats
  GET  /market-scanner/status              scheduler + tick-feed health, last run
  GET  /market-scanner/alerts              recent fired alerts
  POST /market-scanner/alerts/read         mark alerts read
  POST /market-scanner/scan                trigger a sweep now (manual)
  GET  /market-scanner/knowledge           the runtime knowledge config the engine scores with
  POST /market-scanner/knowledge/reload    re-read knowledge.yaml without a restart
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.market_scanner import knowledge, service

router = APIRouter(prefix="/market-scanner", tags=["market-scanner"])


@router.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.recommendations(db)


@router.get("/recommendations/{rec_id}")
def get_recommendation(rec_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    out = service.recommendation_detail(db, rec_id)
    if out is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return out


@router.get("/logbook")
def get_logbook(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    outcome: str | None = Query(None),
    symbol: str | None = Query(None),
    horizon: str | None = Query(None),
    setup: str | None = Query(None),
    direction: str | None = Query(None),
    trade_style: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.logbook(
        db, date_from=date_from, date_to=date_to, outcome=outcome, symbol=symbol,
        horizon=horizon, setup=setup, direction=direction, trade_style=trade_style,
        page=page, page_size=page_size,
    )


@router.get("/status")
def get_status(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    return service.status(db, settings)


@router.get("/alerts")
def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.alerts(db, limit=limit, unread_only=unread_only)


@router.post("/alerts/read")
def post_alerts_read(
    ids: list[str] | None = Body(None, embed=True), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.mark_alerts_read(db, ids)


@router.post("/scan")
async def post_scan(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    return await service.trigger_scan(db, settings)


@router.get("/knowledge")
def get_knowledge() -> dict[str, Any]:
    """The machine-readable knowledge config the scorer reads at runtime.
    Edit backend/app/market_scanner/knowledge.yaml and call the reload
    endpoint (or restart) to retune the engine without a code change."""
    return {"config": knowledge.KB, "source": str(knowledge._YAML_PATH),  # noqa: SLF001
            "yaml_present": knowledge._YAML_PATH.exists()}  # noqa: SLF001


@router.post("/knowledge/reload")
def post_knowledge_reload() -> dict[str, Any]:
    return {"reloaded": True, "config": knowledge.reload()}

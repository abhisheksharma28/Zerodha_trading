"""Live market overview for the Market Scanner.

Real quotes from the connected Zerodha session. Returns ``available: false``
(never fabricated data) when there is no session.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.services import market_data_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview")
def overview(
    universe: str = Query("nifty50", description="Constituent universe for gainers/losers/heatmap"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return market_data_service.market_overview(db, settings, universe=universe)

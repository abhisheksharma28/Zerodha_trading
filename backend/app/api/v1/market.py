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


@router.get("/option-chain")
def option_chain(
    underlying: str = Query(..., description="e.g. NIFTY, BANKNIFTY, RELIANCE"),
    expiry: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return market_data_service.option_chain(db, settings, underlying=underlying, expiry=expiry)


@router.get("/candles")
def candles(
    symbol: str = Query(..., description="e.g. NSE:INFY or INFY"),
    timeframe: str = Query("5m"),
    days: int | None = Query(None, ge=1, le=4000),
    from_date: str | None = Query(None, description="ISO date/datetime — pin the window start"),
    to_date: str | None = Query(None, description="ISO date/datetime — pin the window end"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return market_data_service.candles(
        db, settings, symbol=symbol, timeframe=timeframe, days=days,
        from_date=from_date, to_date=to_date,
    )

"""Stock Intelligence endpoints — a quick-look panel for any NSE instrument.

    GET /api/v1/stocks/{exchange}/{symbol}               profile + live quote + metrics summary
    GET /api/v1/stocks/{exchange}/{symbol}/fundamentals  full fundamentals bundle (lazy-loaded)

Reuses the canonical instrument master; fundamentals come through the
configurable provider abstraction (app.providers.fundamentals).
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.services import stock_service

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/{exchange}/{symbol}")
def get_stock(
    exchange: str,
    symbol: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return stock_service.quick_look(db, settings, exchange, symbol)


@router.get("/{exchange}/{symbol}/fundamentals")
def get_fundamentals(
    exchange: str,
    symbol: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return stock_service.fundamentals(db, settings, exchange, symbol)

"""Market Insights — one briefing that covers the whole platform.

  GET /insights   index + breadth + volatility pulse, sector rotation,
                  the scanner's read, the paper book's state, seasonality
                  context, and a plain-English narrative + takeaways.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.insights import build

router = APIRouter(prefix="/insights", tags=["insights"])

_TTL = 45.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@router.get("")
def get_insights(
    universe: str = Query("nifty100", pattern="^(nifty50|nifty100|nifty200)$"),
    fresh: bool = Query(False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    key = universe
    now = time.monotonic()
    if not fresh:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    with _lock:
        hit = _cache.get(key)
        if not fresh and hit and time.monotonic() - hit[0] < _TTL:
            return hit[1]
        data = build(db, settings, universe=universe)
        _cache[key] = (time.monotonic(), data)
        return data

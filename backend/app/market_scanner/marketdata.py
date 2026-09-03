"""Thin data-access layer for the scanner: candles + batched quotes off the
connected Kite client, with a small in-process cache so a 5-minute sweep
does not re-pull slow-moving daily history every cycle. All calls are
self-throttled by the client's historical / quote rate limiters.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.services import broker_service

logger = get_logger(__name__)

# interval -> (kite token, lookback days, cache TTL seconds)
_PLAN = {
    "day": ("day", 420, 3600),
    "15minute": ("15minute", 9, 240),
    "5minute": ("5minute", 4, 120),
}
_bar_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


def get_client(db: Session, settings: Settings) -> Any | None:
    try:
        return broker_service.build_authenticated_client(db, settings)
    except Exception as exc:  # noqa: BLE001
        logger.info("scanner_no_broker", error=str(exc))
        return None


def _rows_to_bars(rows: list[list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if len(r) < 5:
            continue
        out.append({
            "time": str(r[0]), "open": float(r[1]), "high": float(r[2]),
            "low": float(r[3]), "close": float(r[4]),
            "volume": float(r[5]) if len(r) > 5 and r[5] is not None else 0.0,
        })
    return out


def fetch_bars(client: Any, instrument_token: str, interval: str, *, force: bool = False) -> list[dict[str, Any]]:
    kite_int, days, ttl = _PLAN.get(interval, ("day", 400, 900))
    key = (str(instrument_token), kite_int)
    now = time.monotonic()
    if not force:
        hit = _bar_cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days)
    try:
        rows = client.get_historical_candles(str(instrument_token), kite_int, from_dt, to_dt)
    except Exception as exc:  # noqa: BLE001 - surface upstream, keep scanning others
        logger.info("scanner_candle_fetch_failed", token=instrument_token, interval=kite_int, error=str(exc))
        return []
    bars = _rows_to_bars(rows)
    _bar_cache[key] = (now, bars)
    return bars


def batched_quotes(client: Any, refs: list[str], *, chunk: int = 200) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(refs), chunk):
        part = refs[i : i + chunk]
        try:
            data = client.get_quote(part)
        except Exception as exc:  # noqa: BLE001
            logger.info("scanner_quote_chunk_failed", n=len(part), error=str(exc))
            continue
        for k, v in (data or {}).items():
            out[k] = v
    return out


def quote_ltp(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    v = row.get("last_price")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def quote_screen_score(row: dict[str, Any] | None) -> tuple[float, dict[str, Any]] | None:
    """Cheap 0-100 'worth a full look' score from a single quote: net change,
    where price sits in the day range, and last-vs-open push. No history."""
    if not row:
        return None
    ltp = quote_ltp(row)
    ohlc = row.get("ohlc") or {}
    o, h, lo = ohlc.get("open"), ohlc.get("high"), ohlc.get("low")
    prev_close = ohlc.get("close")
    if not ltp or not o or not h or not lo or h <= lo:
        return None
    chg_pct = 100.0 * (ltp - prev_close) / prev_close if prev_close else 0.0
    range_pos = (ltp - lo) / (h - lo)  # 0 at low, 1 at high
    push = 100.0 * (ltp - o) / o if o else 0.0
    score = min(100.0, abs(chg_pct) * 12 + abs(push) * 8 + abs(range_pos - 0.5) * 40)
    meta = {"chg_pct": round(chg_pct, 2), "range_pos": round(range_pos, 2), "push_pct": round(push, 2)}
    return score, meta


def clear_cache() -> None:
    _bar_cache.clear()

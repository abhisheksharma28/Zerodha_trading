"""Shared candle pool for the leaderboard's dynamic universe screens.

A test plan screens the *market* to pick the names that fit its strategy, so
the screen needs bars for a broad candidate set before any single backtest
runs. This module fetches that pool once (daily bars for the liquid NSE cash
list plus the sector / broad indices), leaning entirely on the file-backed
candle cache so a second call is almost free and a first call is resumable.

Kite's history API is metered (~3 req/s), so uncached pulls are paced.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.backtesting.timeframes import kite_interval, resolve
from app.config import Settings
from app.core.logging import get_logger
from app.market_data.cache import get_candles, is_cached
from app.market_data.instruments import resolve_instrument_token
from app.market_data.nse_universe import BROAD_INDICES, SECTOR_INDICES
from app.market_scanner.universe import build as build_scan_universe
from app.services import broker_service
from app.strategies.base import Bar

logger = get_logger(__name__)

_PACE_SECONDS = 0.34  # ~3 req/s for uncached history pulls


def candidate_symbols(db: Session, *, max_equities: int = 400) -> list[str]:
    """Bare tradingsymbols for the screen pool: liquid NSE cash equities
    (most-liquid first) plus the NSE sector and broad indices."""
    uni = build_scan_universe(db)
    equities = [i.tradingsymbol for i in uni.all if i.asset_class == "EQUITY"]
    seen: set[str] = set()
    ordered: list[str] = []
    for s in [*equities[:max_equities], *SECTOR_INDICES, *BROAD_INDICES]:
        u = s.strip().upper()
        if u not in seen:
            seen.add(u)
            ordered.append(s)
    return ordered


def load_pool(
    db: Session,
    settings: Settings,
    *,
    as_of: str,
    years: float,
    timeframe: str = "1d",
    max_equities: int = 400,
) -> tuple[dict[str, list[Bar]], dict[str, str]]:
    """Return ``({tradingsymbol: bars <= as_of}, {symbol: skip_reason})``.

    Bars come from the on-disk candle cache where present; only misses hit
    Kite, paced. ``as_of`` is an ISO date (the backtest end); the window is
    ``years`` back from it.
    """
    tf = resolve(timeframe)
    interval = kite_interval(tf.token)
    to_dt = datetime.fromisoformat(as_of).replace(tzinfo=None)
    from_dt = to_dt - timedelta(days=int(years * 365.25))
    client = broker_service.build_authenticated_client(db, settings)

    symbols = candidate_symbols(db, max_equities=max_equities)
    bars: dict[str, list[Bar]] = {}
    skipped: dict[str, str] = {}
    fetched = 0
    for sym in symbols:
        try:
            token, tradingsymbol = resolve_instrument_token(sym)
        except Exception:  # noqa: BLE001
            skipped[sym] = "not in instrument master"
            continue
        cached = is_cached(token, interval, from_dt, to_dt)
        try:
            got = get_candles(client, token, tradingsymbol, interval, from_dt, to_dt)
        except Exception as exc:  # noqa: BLE001
            skipped[sym] = f"history unavailable: {exc}"
            continue
        if not got:
            skipped[sym] = "no candles in window"
            continue
        bars[tradingsymbol] = got
        if not cached:
            fetched += 1
            time.sleep(_PACE_SECONDS)  # pace only the metered pulls

    logger.info("leaderboard_pool_loaded", symbols=len(bars), skipped=len(skipped),
                as_of=as_of, years=years)
    return bars, skipped

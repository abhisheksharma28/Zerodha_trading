"""Background loops for the Market Scanner, run from the API process
lifespan (co-located with the Kite tick feed).

* scan loop    - every ``scan_interval`` during market hours: sweep the
                 universe, persist LIVE recommendations, subscribe their
                 instruments on the tick feed.
* tracker loop - every ``track_interval`` while any LIVE row exists: mark
                 against the real-time price, resolve target / stop / EOD.

A Postgres advisory lock makes exactly one process run the loops even if
the API is started with several workers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.market_scanner import scanner, tracker
from app.models.market_scanner import ScanRecommendation

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_SCAN_LOCK_KEY = 776610  # arbitrary, unique to this feature
# Equity 09:15-15:30; commodities trade later but the scanner's tracked set
# is equity/index-heavy, so we keep new scans to the equity session and let
# the tracker run a bit past close for the EOD flatten.
_SESSION_START = dtime(9, 15)
_SCAN_STOP = dtime(15, 20)
_TRACK_STOP = dtime(15, 45)

_stop = asyncio.Event()


def market_phase(now_ist: datetime | None = None) -> str:
    now = now_ist or datetime.now(IST)
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if t < _SESSION_START or t >= _TRACK_STOP:
        return "closed"
    if t >= _SCAN_STOP:
        return "tracking_only"
    return "open"


def _try_lock(db: Session) -> bool:
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _SCAN_LOCK_KEY}).scalar())


def _unlock(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SCAN_LOCK_KEY})
    db.commit()


async def _subscribe_live_tokens(db: Session) -> None:
    tokens = [
        int(t) for t in db.execute(
            select(ScanRecommendation.instrument_token).where(ScanRecommendation.status == "LIVE")
        ).scalars().all()
        if str(t).isdigit()
    ]
    if not tokens:
        return
    try:
        from app.live import engine as live_engine

        await live_engine.ensure_system_subscription(tokens)
    except Exception:  # noqa: BLE001 - the feed is best-effort; tracker falls back to REST
        logger.info("scanner_tick_subscribe_skipped")


def run_scan_cycle(db: Session, settings: Settings, *, trigger: str = "schedule") -> scanner.ScanOutcome:
    return scanner.run_scan(db, settings, trigger=trigger)


def run_tracker_cycle(db: Session, settings: Settings) -> tracker.TrackOutcome:
    return tracker.run_tracker(db, settings)


async def _loop() -> None:
    settings = get_settings()
    db = SessionLocal()
    if not _try_lock(db):
        logger.info("market_scanner_loop_not_leader")
        db.close()
        return
    logger.info("market_scanner_loop_started",
                scan_every=settings.market_scanner_scan_interval_seconds,
                track_every=settings.market_scanner_track_interval_seconds)
    last_scan = 0.0
    try:
        while not _stop.is_set():
            loop_now = asyncio.get_event_loop().time()
            phase = market_phase()
            try:
                if phase == "open" and loop_now - last_scan >= settings.market_scanner_scan_interval_seconds:
                    await asyncio.to_thread(run_scan_cycle, db, settings)
                    last_scan = loop_now
                    await _subscribe_live_tokens(db)
                if phase in ("open", "tracking_only"):
                    await asyncio.to_thread(run_tracker_cycle, db, settings)
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.exception("market_scanner_cycle_error")
                db.rollback()
            await asyncio.wait(
                [asyncio.create_task(_stop.wait())],
                timeout=settings.market_scanner_track_interval_seconds,
            )
    finally:
        _unlock(db)
        db.close()
        logger.info("market_scanner_loop_stopped")


_task: asyncio.Task[None] | None = None


async def start() -> None:
    global _task
    if not get_settings().market_scanner_enabled or _task is not None:
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="market-scanner")


async def stop() -> None:
    global _task
    _stop.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None

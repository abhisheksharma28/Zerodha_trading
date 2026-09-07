"""Daily background sweep for the Stock Screener, run from the API-process
lifespan. One worker wins a Postgres advisory lock; it runs a sweep once
per calendar day, on or after ``screener_sweep_hour_ist`` (default 16:00
IST — after the cash close, so the day's candles are final). A sweep also
runs on first boot if none has happened today yet.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.config import get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.screener import ScreenerRun
from app.screener import engine

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_LOCK_KEY = 776641
_POLL_SECONDS = 900.0  # re-check every 15 min

_stop = asyncio.Event()
_task: asyncio.Task[None] | None = None


def _ran_today(db) -> bool:  # noqa: ANN001
    today = datetime.now(IST).date()
    last = db.execute(
        select(ScreenerRun.started_at)
        .where(ScreenerRun.finished_at.is_not(None), ScreenerRun.error.is_(None))
        .order_by(ScreenerRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return last is not None and last.astimezone(IST).date() >= today


def _due() -> bool:
    return datetime.now(IST).hour >= get_settings().screener_sweep_hour_ist


async def _loop() -> None:
    settings = get_settings()
    while not _stop.is_set():
        db = SessionLocal()
        try:
            got = bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar())
            if not got:
                db.close()
                await _sleep_or_stop(_POLL_SECONDS)
                continue
            logger.info("screener_scheduler_started")
            while not _stop.is_set():
                try:
                    if settings.screener_enabled and _due() and not _ran_today(db):
                        logger.info("screener_daily_sweep_begin")
                        await asyncio.to_thread(engine.run_sweep, db, settings, trigger="schedule")
                except Exception:  # noqa: BLE001 - never let the loop die
                    logger.exception("screener_scheduler_tick_error")
                    db.rollback()
                await _sleep_or_stop(_POLL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception("screener_scheduler_loop_crashed")
        finally:
            with contextlib.suppress(Exception):
                db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                db.commit()
            db.close()
        if not _stop.is_set():
            await _sleep_or_stop(60.0)
    logger.info("screener_scheduler_stopped")


async def _sleep_or_stop(seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_stop.wait(), timeout=seconds)


async def start() -> None:
    global _task
    if _task is not None:
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="screener-scheduler")


async def stop() -> None:
    global _task
    _stop.set()
    if _task is not None:
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(_task, timeout=5)
        _task = None

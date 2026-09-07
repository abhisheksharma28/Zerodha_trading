"""Background delivery loop for outbound notifications.

Runs from the API-process lifespan. A Postgres advisory lock elects one
runner across uvicorn workers / replicas. Every ~10 s it delivers any
``pending`` outbox rows to Telegram and, once per day after 15:35 IST,
enqueues the paper-account daily summary.

Deliberately *not* market-hours gated: paper fills, square-offs and the
end-of-day summary all happen at or after the close.
"""

from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy import text

from app.config import get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.notifications import service

logger = get_logger(__name__)

_LOCK_KEY = 776630
_TICK_SECONDS = 10.0
_stop = asyncio.Event()
_task: asyncio.Task[None] | None = None


def _run_cycle(db, settings) -> None:
    service.dispatch_pending(db, settings)
    try:
        service.maybe_send_daily_summary(db, settings)
    except Exception:  # noqa: BLE001 - the summary must not stall delivery
        logger.exception("notifications_daily_summary_error")
        db.rollback()


async def _sleep_or_stop(seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_stop.wait(), timeout=seconds)


async def _loop() -> None:
    settings = get_settings()
    while not _stop.is_set():
        db = SessionLocal()
        try:
            if not bool(
                db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar()
            ):
                db.close()
                await _sleep_or_stop(45.0)
                continue
            with contextlib.suppress(Exception):
                service.get_config(db)  # materialise the row once, off the trade path
            logger.info("notifications_loop_started")
            while not _stop.is_set():
                try:
                    await asyncio.to_thread(_run_cycle, db, settings)
                except Exception:  # noqa: BLE001
                    logger.exception("notifications_cycle_error")
                    db.rollback()
                await _sleep_or_stop(_TICK_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception("notifications_loop_crashed")
        finally:
            with contextlib.suppress(Exception):
                db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                db.commit()
            db.close()
        if not _stop.is_set():
            await _sleep_or_stop(15.0)
    logger.info("notifications_loop_stopped")


async def start() -> None:
    global _task
    if _task is not None:
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="notifications")


async def stop() -> None:
    global _task
    _stop.set()
    if _task is not None:
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(_task, timeout=5)
        _task = None

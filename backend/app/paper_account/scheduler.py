"""Background loop for the paper account, run from the API-process lifespan
(so it can read the in-process tick feed).

Every few seconds while the market is open, and only on the one process
that wins a Postgres advisory lock:

  * fill resting LIMIT / SL / SL-M orders when the live price crosses,
  * refresh the marked price on open positions & holdings,
  * at 15:20 IST auto-square-off every MIS position,
  * once after the close, settle T1 holdings and roll the day.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.paper_account import PaperHolding, PaperOrder, PaperPosition
from app.paper_account import engine, pricing
from app.paper_account.engine import OrderRequest, get_or_create_account

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_LOCK_KEY = 776620
_SESSION_START = dtime(9, 15)
_MIS_SQUAREOFF = dtime(15, 20)
_SESSION_END = dtime(15, 40)
_TICK_SECONDS = 5.0
_stop = asyncio.Event()
_task: asyncio.Task[None] | None = None


def _phase(now: datetime | None = None) -> str:
    n = now or datetime.now(IST)
    if n.weekday() >= 5:
        return "closed"
    t = n.time()
    if t < _SESSION_START or t >= _SESSION_END:
        return "closed"
    return "squareoff" if t >= _MIS_SQUAREOFF else "open"


def _price_for(order: PaperOrder, ltp: float) -> float | None:
    """Return a fill price if this resting order should trigger at ``ltp``."""
    buy = order.side == "BUY"
    limit_px = float(order.price) if order.price is not None else None
    trig_px = float(order.trigger_price) if order.trigger_price is not None else None
    if order.order_type == "LIMIT":
        if limit_px is None:
            return None
        if buy and ltp <= limit_px:
            return min(ltp, limit_px)
        if not buy and ltp >= limit_px:
            return max(ltp, limit_px)
        return None
    if trig_px is None:
        return None
    hit = (buy and ltp >= trig_px) or (not buy and ltp <= trig_px)
    if not hit:
        return None
    if order.order_type == "SL" and limit_px is not None:
        return limit_px
    return ltp  # SL-M


def _fill_resting(db: Session, settings: Settings) -> int:
    acct = get_or_create_account(db)
    open_orders = list(db.execute(
        select(PaperOrder).where(PaperOrder.account_id == acct.id, PaperOrder.status == "OPEN")
    ).scalars().all())
    if not open_orders:
        return 0
    qmap = pricing.quotes(db, settings, [
        {"ref": f"{o.exchange}:{o.tradingsymbol}", "token": o.instrument_token} for o in open_orders
    ])
    n = 0
    for o in open_orders:
        q = qmap.get(f"{o.exchange}:{o.tradingsymbol}")
        if not q or q.ltp is None:
            continue
        px = _price_for(o, q.ltp)
        if px is None:
            continue
        engine._try_fill(db, acct, o, px, q.prev_close)  # noqa: SLF001
        n += 1
    if n:
        db.commit()
    return n


def _squareoff_mis(db: Session, settings: Settings) -> int:
    acct = get_or_create_account(db)
    if not acct.auto_squareoff_mis:
        return 0
    mis = list(db.execute(
        select(PaperPosition).where(
            PaperPosition.account_id == acct.id, PaperPosition.status == "OPEN",
            PaperPosition.product == "MIS", PaperPosition.net_qty != 0,
        )
    ).scalars().all())
    n = 0
    for p in mis:
        order = engine.place_order(db, settings, OrderRequest(
            exchange=p.exchange, tradingsymbol=p.tradingsymbol,
            side="SELL" if p.net_qty > 0 else "BUY", quantity=abs(p.net_qty),
            order_type="MARKET", product="MIS", tag="mis-squareoff",
        ))
        order.is_squareoff = True
        n += 1
    if n:
        db.commit()
        logger.info("paper_mis_squareoff", positions=n)
    return n


def _eod_roll(db: Session) -> None:
    acct = get_or_create_account(db)
    today = datetime.now(IST).date().isoformat()
    if acct.last_eod_day == today:
        return
    for h in db.execute(
        select(PaperHolding).where(PaperHolding.account_id == acct.id, PaperHolding.t1_qty > 0)
    ).scalars().all():
        h.t1_qty = 0
    acct.last_eod_day = today
    db.commit()
    logger.info("paper_eod_roll", day=today)


def run_cycle(db: Session, settings: Settings) -> None:
    phase = _phase()
    if phase == "closed":
        _eod_roll(db)
        return
    _fill_resting(db, settings)
    try:
        from app.paper_account import strategies

        strategies.tick_all(db, settings)
    except Exception:  # noqa: BLE001 - strategy runner must not break the loop
        logger.exception("paper_strategy_tick_all_error")
        db.rollback()
    try:
        from app.paper_account import algo

        algo.run_once(db, settings)
        algo.manage(db, settings)
    except Exception:  # noqa: BLE001 - the auto-trade bridge must not break the loop
        logger.exception("paper_algo_cycle_error")
        db.rollback()
    try:
        from app.baskets import paper as basket_paper

        basket_paper.tick_all(db, settings)
    except Exception:  # noqa: BLE001 - basket rebalancing must not break the loop
        logger.exception("basket_tick_all_error")
        db.rollback()
    if phase == "squareoff":
        _squareoff_mis(db, settings)
    # keep tokens flowing on the tick feed
    with contextlib.suppress(Exception):
        acct = get_or_create_account(db)
        tokens = [
            int(t) for t in db.execute(
                select(PaperPosition.instrument_token).where(
                    PaperPosition.account_id == acct.id, PaperPosition.status == "OPEN"
                )
            ).scalars().all()
            if t and str(t).isdigit()
        ]
        if tokens:
            from app.live import engine as live_engine

            asyncio.get_event_loop().create_task(live_engine.ensure_system_subscription(tokens))


async def _sleep_or_stop(seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_stop.wait(), timeout=seconds)


async def _loop() -> None:
    settings = get_settings()
    while not _stop.is_set():
        db = SessionLocal()
        try:
            if not bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar()):
                db.close()
                await _sleep_or_stop(45.0)
                continue
            logger.info("paper_account_loop_started")
            while not _stop.is_set():
                try:
                    await asyncio.to_thread(run_cycle, db, settings)
                except Exception:  # noqa: BLE001
                    logger.exception("paper_account_cycle_error")
                    db.rollback()
                await _sleep_or_stop(_TICK_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception("paper_account_loop_crashed")
        finally:
            with contextlib.suppress(Exception):
                db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                db.commit()
            db.close()
        if not _stop.is_set():
            await _sleep_or_stop(15.0)
    logger.info("paper_account_loop_stopped")


async def start() -> None:
    global _task
    if _task is not None:
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="paper-account")


async def stop() -> None:
    global _task
    _stop.set()
    if _task is not None:
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(_task, timeout=5)
        _task = None

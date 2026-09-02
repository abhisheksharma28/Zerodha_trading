"""Broker <-> OMS <-> DB reconciliation.

Runs on every worker poll while there is a broker session and the OMS has
open orders. It reads the broker's own order book (the source of truth),
folds each into the OMS, and mirrors terminal outcomes onto the ``orders``
row plus a ``Trade`` on fill. It also tries to adopt an order that a
client-side submit timeout left untracked — a timeout is never assumed to
mean the order failed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.live.oms import CANCELLED, FAILED, FILLED, OMS_ENGINE, REJECTED
from app.live.risk import RISK
from app.models.enums import OrderStatus, TradingMode
from app.models.order import Order, Trade

logger = get_logger(__name__)

_STATE_TO_DB = {
    FILLED: OrderStatus.COMPLETE,
    REJECTED: OrderStatus.REJECTED,
    CANCELLED: OrderStatus.CANCELLED,
    FAILED: OrderStatus.REJECTED,
}


def reconcile(db: Session, broker_client: Any) -> dict[str, int]:
    open_orders = OMS_ENGINE.open_orders()
    if not open_orders:
        return {"checked": 0, "settled": 0}

    try:
        broker_orders = broker_client.get_orders()
    except Exception as exc:  # noqa: BLE001 - a bad poll must not kill the worker
        logger.warning("reconcile_get_orders_failed", error=str(exc))
        return {"checked": len(open_orders), "settled": 0, "error": 1}

    OMS_ENGINE.adopt_unclaimed(broker_orders)

    settled = 0
    for bo in broker_orders:
        done = OMS_ENGINE.apply_broker_status(bo)
        if done is None:
            continue
        settled += 1
        _persist_terminal(db, done)

    return {"checked": len(open_orders), "settled": settled}


def _persist_terminal(db: Session, oms_order: Any) -> None:
    row = db.get(Order, oms_order.internal_id)
    if row is None:
        return
    new_status = _STATE_TO_DB.get(oms_order.state)
    if new_status is None or row.status == new_status:
        return

    row.status = new_status
    row.status_message = (oms_order.reject_reason or "")[:1000] or row.status_message
    row.raw_response = {
        **(row.raw_response or {}),
        "oms": oms_order.as_dict(),
    }

    if oms_order.state == FILLED:
        already = db.query(Trade).filter(Trade.order_id == row.id).count()
        if already == 0:
            db.add(
                Trade(
                    order_id=row.id,
                    mode=TradingMode.LIVE,
                    fill_price=round(float(oms_order.avg_fill_price or 0.0), 4),
                    fill_quantity=int(oms_order.filled_qty or oms_order.quantity),
                    fill_time=datetime.now(UTC),
                )
            )
        RISK.record_fill(
            oms_order.deployment_id,
            oms_order.tradingsymbol,
            oms_order.side,
            int(oms_order.filled_qty or oms_order.quantity),
        )

    logger.info(
        "reconcile_order_settled",
        internal_id=oms_order.internal_id,
        state=oms_order.state,
        broker_order_id=oms_order.broker_order_id,
    )

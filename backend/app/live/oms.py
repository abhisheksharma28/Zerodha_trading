"""In-memory Order Management System — the lifecycle + reconciliation layer
that sits above the ``orders`` table.

The DB ``OrderStatus`` enum is deliberately coarse (PENDING/OPEN/COMPLETE/
REJECTED/CANCELLED). The OMS tracks the finer institutional lifecycle
(CREATED → SUBMITTED → ACKNOWLEDGED → OPEN → PARTIALLY_FILLED → FILLED, plus
REJECTED/CANCELLED/FAILED) with per-transition monotonic + wall timestamps,
so:

* a worker retry can't double-submit an order that is already in flight,
* a client-side timeout is never assumed to be a failure — the reconciler
  reads the broker's order book and is the source of truth for fills,
* every stage is timestamped for the latency monitor.

State lives only in memory; the reconciler mirrors terminal outcomes onto
the ``Order`` row.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# --- states -----------------------------------------------------------

CREATED = "CREATED"
SUBMITTED = "SUBMITTED"
ACKNOWLEDGED = "ACKNOWLEDGED"
OPEN = "OPEN"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
FAILED = "FAILED"

TERMINAL = {FILLED, REJECTED, CANCELLED, FAILED}

_ALLOWED: dict[str, set[str]] = {
    CREATED: {SUBMITTED, REJECTED, FAILED},
    SUBMITTED: {ACKNOWLEDGED, OPEN, PARTIALLY_FILLED, FILLED, REJECTED, CANCELLED, FAILED},
    ACKNOWLEDGED: {OPEN, PARTIALLY_FILLED, FILLED, REJECTED, CANCELLED, FAILED},
    OPEN: {PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, FAILED},
    PARTIALLY_FILLED: {PARTIALLY_FILLED, FILLED, CANCELLED, FAILED},
}

# Kite order "status" -> OMS state
_KITE_MAP = {
    "COMPLETE": FILLED,
    "REJECTED": REJECTED,
    "CANCELLED": CANCELLED,
    "OPEN": OPEN,
    "TRIGGER PENDING": OPEN,
    "AMO REQ RECEIVED": SUBMITTED,
    "PUT ORDER REQ RECEIVED": SUBMITTED,
    "VALIDATION PENDING": SUBMITTED,
    "MODIFY VALIDATION PENDING": OPEN,
    "OPEN PENDING": SUBMITTED,
}


class InvalidTransition(RuntimeError):
    pass


@dataclass
class OMSOrder:
    internal_id: str
    deployment_id: str
    tradingsymbol: str
    exchange: str
    side: str  # BUY | SELL
    quantity: int
    state: str = CREATED
    broker_order_id: str | None = None
    filled_qty: int = 0
    avg_fill_price: float | None = None
    reject_reason: str | None = None
    # wall-clock for display, perf_counter_ns for latency deltas
    t_created_ns: int = field(default_factory=time.perf_counter_ns)
    t_submitted_ns: int | None = None
    t_ack_ns: int | None = None
    t_filled_ns: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    submitted_at: str | None = None
    filled_at: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    def as_dict(self) -> dict[str, Any]:
        def ms(a: int | None, b: int | None) -> float | None:
            return round((b - a) / 1e6, 3) if (a is not None and b is not None) else None

        return {
            "internal_id": self.internal_id,
            "deployment_id": self.deployment_id,
            "tradingsymbol": self.tradingsymbol,
            "side": self.side,
            "quantity": self.quantity,
            "state": self.state,
            "broker_order_id": self.broker_order_id,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at,
            "submitted_at": self.submitted_at,
            "filled_at": self.filled_at,
            "latency_ms": {
                "create_to_submit": ms(self.t_created_ns, self.t_submitted_ns),
                "submit_to_ack": ms(self.t_submitted_ns, self.t_ack_ns),
                "submit_to_fill": ms(self.t_submitted_ns, self.t_filled_ns),
            },
        }


class OMS:
    def __init__(self) -> None:
        self._orders: dict[str, OMSOrder] = {}
        self._lock = threading.Lock()

    # --- lifecycle -------------------------------------------------

    def register(
        self,
        internal_id: str,
        *,
        deployment_id: str,
        tradingsymbol: str,
        exchange: str,
        side: str,
        quantity: int,
    ) -> OMSOrder:
        with self._lock:
            o = OMSOrder(
                internal_id=internal_id,
                deployment_id=deployment_id,
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                side=side.upper(),
                quantity=int(quantity),
            )
            self._orders[internal_id] = o
            return o

    def in_flight_fingerprint(self, deployment_id: str, tradingsymbol: str, side: str, qty: int) -> bool:
        """True if an equivalent order is already CREATED/SUBMITTED/OPEN —
        lets the router refuse a retry double-submit."""
        with self._lock:
            return any(
                not o.terminal
                and o.deployment_id == deployment_id
                and o.tradingsymbol == tradingsymbol
                and o.side == side.upper()
                and o.quantity == int(qty)
                for o in self._orders.values()
            )

    def _transition(self, o: OMSOrder, new: str) -> None:
        if o.state == new:
            return
        allowed = _ALLOWED.get(o.state, set())
        if new not in allowed:
            raise InvalidTransition(f"{o.internal_id}: {o.state} -> {new} not allowed")
        o.state = new

    def mark_submitted(self, internal_id: str, broker_order_id: str | None) -> None:
        with self._lock:
            o = self._orders.get(internal_id)
            if o is None:
                return
            self._transition(o, SUBMITTED)
            o.broker_order_id = broker_order_id
            o.t_submitted_ns = time.perf_counter_ns()
            o.submitted_at = datetime.now(UTC).isoformat()

    def mark_failed(self, internal_id: str, reason: str) -> None:
        with self._lock:
            o = self._orders.get(internal_id)
            if o is None or o.terminal:
                return
            o.state = FAILED
            o.reject_reason = reason

    def mark_rejected(self, internal_id: str, reason: str) -> None:
        with self._lock:
            o = self._orders.get(internal_id)
            if o is None:
                return
            o.state = REJECTED
            o.reject_reason = reason

    def apply_broker_status(self, broker_order: dict[str, Any]) -> OMSOrder | None:
        """Fold a Kite order dict into the matching OMS order. Returns the
        order if it moved to a terminal state (so the caller can persist)."""
        boid = str(broker_order.get("order_id") or "")
        if not boid:
            return None
        with self._lock:
            o = next((x for x in self._orders.values() if x.broker_order_id == boid), None)
            if o is None or o.terminal:
                return None
            kite_status = str(broker_order.get("status") or "").upper()
            new = _KITE_MAP.get(kite_status)
            filled = int(broker_order.get("filled_quantity") or 0)
            avg = broker_order.get("average_price")

            if filled and not o.terminal:
                o.filled_qty = filled
                o.avg_fill_price = float(avg) if avg else o.avg_fill_price
                if o.t_ack_ns is None:
                    o.t_ack_ns = time.perf_counter_ns()
                if filled >= o.quantity:
                    new = FILLED
                elif new not in TERMINAL:
                    new = PARTIALLY_FILLED

            if new is None:
                return None
            if new == REJECTED:
                o.reject_reason = str(broker_order.get("status_message") or "rejected by broker")
            became_terminal = new in TERMINAL
            if new == FILLED:
                o.t_filled_ns = time.perf_counter_ns()
                o.filled_at = datetime.now(UTC).isoformat()
                o.state = FILLED
            elif new in TERMINAL:
                o.state = new
            else:
                try:
                    self._transition(o, new)
                except InvalidTransition:
                    return None
            return o if became_terminal else None

    def adopt_unclaimed(self, broker_orders: list[dict[str, Any]], *, max_age_seconds: float = 600.0) -> None:
        """Best-effort recovery after a submit timeout: a SUBMITTED OMS order
        with no broker_order_id gets matched to a recent broker order with
        the same symbol/side/qty that nothing else is tracking."""
        with self._lock:
            known = {o.broker_order_id for o in self._orders.values() if o.broker_order_id}
            orphans = [
                o for o in self._orders.values()
                if o.broker_order_id is None and o.state == SUBMITTED and not o.terminal
            ]
            for o in orphans:
                for bo in broker_orders:
                    boid = str(bo.get("order_id") or "")
                    if not boid or boid in known:
                        continue
                    if (
                        str(bo.get("tradingsymbol", "")).upper() == o.tradingsymbol.upper()
                        and str(bo.get("transaction_type", "")).upper() == o.side
                        and int(bo.get("quantity") or 0) == o.quantity
                    ):
                        o.broker_order_id = boid
                        known.add(boid)
                        logger.warning(
                            "oms_adopted_unclaimed_order",
                            internal_id=o.internal_id,
                            broker_order_id=boid,
                        )
                        break

    # --- queries -------------------------------------------------

    def open_orders(self) -> list[OMSOrder]:
        with self._lock:
            return [o for o in self._orders.values() if not o.terminal]

    def get(self, internal_id: str) -> OMSOrder | None:
        return self._orders.get(internal_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            orders = [o.as_dict() for o in self._orders.values()]
        by_state: dict[str, int] = {}
        for o in orders:
            by_state[o["state"]] = by_state.get(o["state"], 0) + 1
        return {
            "counts": by_state,
            "open": sum(1 for o in orders if o["state"] not in TERMINAL),
            "orders": sorted(orders, key=lambda x: x["created_at"], reverse=True)[:100],
        }

    def reset(self) -> None:  # test hook
        with self._lock:
            self._orders.clear()


OMS_ENGINE = OMS()

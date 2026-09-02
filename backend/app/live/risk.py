"""In-memory pre-trade risk engine.

Sits directly in front of execution (app.execution.router.OrderRouter): every
order intent — LIVE, PAPER and SIMULATION alike, so paper stays a faithful
rehearsal — is checked here before it reaches an executor or the broker. The
engine always overrides the strategy: a breach means the order is recorded
REJECTED, not placed, and the deployment keeps running.

All state is in memory and O(1) to consult (rolling deques, running
counters). Nothing here touches the database on the decision path.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.brokers.base import OrderRequest
from app.config import Settings


@dataclass(frozen=True)
class RiskLimits:
    max_order_quantity: int = 0            # 0 = no cap
    max_order_notional_inr: float = 0.0
    max_position_qty_per_instrument: int = 0
    max_open_positions: int = 0
    max_orders_per_second: int = 5
    max_orders_per_minute: int = 200
    max_orders_per_day: int = 1000
    max_daily_loss_inr: float = 0.0        # 0 = no cap; positive number
    duplicate_window_seconds: float = 2.0

    @classmethod
    def from_settings(cls, s: Settings, overrides: dict[str, Any] | None = None) -> RiskLimits:
        base = cls(
            max_order_notional_inr=s.risk_max_live_order_value_inr,
            max_orders_per_second=s.risk_max_orders_per_second,
            max_orders_per_minute=s.risk_max_orders_per_minute,
            max_orders_per_day=s.risk_max_orders_per_day,
        )
        if not overrides:
            return base
        fields = set(cls.__dataclass_fields__)
        clean = {k: overrides[k] for k in overrides if k in fields}
        return cls(**{**base.__dict__, **clean})


@dataclass
class _DeploymentRisk:
    order_times: deque[float] = field(default_factory=lambda: deque(maxlen=4096))
    orders_today: int = 0
    day: date = field(default_factory=lambda: datetime.now(UTC).date())
    positions: dict[str, int] = field(default_factory=dict)
    day_realized_pnl: float = 0.0
    recent: deque[tuple[str, float]] = field(default_factory=lambda: deque(maxlen=256))
    killed: bool = False
    last_reject: str | None = None

    def roll_day_if_needed(self) -> None:
        today = datetime.now(UTC).date()
        if today != self.day:
            self.day = today
            self.orders_today = 0
            self.day_realized_pnl = 0.0
            self.order_times.clear()
            self.recent.clear()


@dataclass
class RiskDecision:
    approved: bool
    reason: str | None = None
    checks: list[str] = field(default_factory=list)


def _fingerprint(o: OrderRequest) -> str:
    return f"{o.tradingsymbol}|{o.transaction_type}|{o.quantity}|{o.order_type}|{o.price}"


class RiskEngine:
    def __init__(self) -> None:
        self._by_deployment: dict[str, _DeploymentRisk] = {}
        self._global_kill = False
        self._lock = threading.Lock()

    # --- state accessors -----------------------------------------------

    def _state(self, deployment_id: str) -> _DeploymentRisk:
        st = self._by_deployment.get(deployment_id)
        if st is None:
            st = _DeploymentRisk()
            self._by_deployment[deployment_id] = st
        st.roll_day_if_needed()
        return st

    # --- kill switch -------------------------------------------------

    def kill(self, deployment_id: str) -> None:
        with self._lock:
            self._state(deployment_id).killed = True

    def resume(self, deployment_id: str) -> None:
        with self._lock:
            self._state(deployment_id).killed = False

    def kill_all(self) -> None:
        with self._lock:
            self._global_kill = True

    def resume_all(self) -> None:
        with self._lock:
            self._global_kill = False

    @property
    def global_kill(self) -> bool:
        return self._global_kill

    # --- the check (called on the decision path) ---------------------

    def evaluate(
        self,
        deployment_id: str,
        order: OrderRequest,
        limits: RiskLimits,
        *,
        now: float | None = None,
    ) -> RiskDecision:
        now = time.time() if now is None else now
        with self._lock:
            st = self._state(deployment_id)
            checks: list[str] = []

            if self._global_kill:
                return RiskDecision(False, "global kill switch is engaged", checks)
            if st.killed:
                return RiskDecision(False, f"kill switch engaged for deployment {deployment_id}", checks)

            qty = int(order.quantity)
            if limits.max_order_quantity and qty > limits.max_order_quantity:
                return RiskDecision(
                    False, f"order qty {qty} > max {limits.max_order_quantity}", checks
                )
            checks.append("order_qty")

            if limits.max_order_notional_inr and order.price is not None:
                notional = float(order.price) * qty
                if notional > limits.max_order_notional_inr:
                    return RiskDecision(
                        False,
                        f"order notional ₹{notional:,.0f} > max ₹{limits.max_order_notional_inr:,.0f}",
                        checks,
                    )
            checks.append("order_notional")

            # order-frequency: per second / minute / day
            recent_1s = sum(1 for t in st.order_times if now - t < 1.0)
            recent_60s = sum(1 for t in st.order_times if now - t < 60.0)
            if limits.max_orders_per_second and recent_1s >= limits.max_orders_per_second:
                return RiskDecision(False, f"order rate {recent_1s}/s ≥ {limits.max_orders_per_second}/s", checks)
            if limits.max_orders_per_minute and recent_60s >= limits.max_orders_per_minute:
                return RiskDecision(
                    False, f"order rate {recent_60s}/min ≥ {limits.max_orders_per_minute}/min", checks
                )
            if limits.max_orders_per_day and st.orders_today >= limits.max_orders_per_day:
                return RiskDecision(
                    False, f"daily order count {st.orders_today} ≥ {limits.max_orders_per_day}", checks
                )
            checks.append("order_frequency")

            # duplicate guard
            fp = _fingerprint(order)
            if any(f == fp and now - t < limits.duplicate_window_seconds for f, t in st.recent):
                return RiskDecision(
                    False,
                    f"duplicate order within {limits.duplicate_window_seconds:g}s",
                    checks,
                )
            checks.append("duplicate")

            # position caps (projected)
            signed = qty if order.transaction_type.upper() == "BUY" else -qty
            projected = st.positions.get(order.tradingsymbol, 0) + signed
            if (
                limits.max_position_qty_per_instrument
                and abs(projected) > limits.max_position_qty_per_instrument
            ):
                return RiskDecision(
                    False,
                    f"projected position {projected} on {order.tradingsymbol} "
                    f"exceeds ±{limits.max_position_qty_per_instrument}",
                    checks,
                )
            if limits.max_open_positions:
                open_after = {
                    s: q
                    for s, q in {**st.positions, order.tradingsymbol: projected}.items()
                    if q != 0
                }
                if len(open_after) > limits.max_open_positions:
                    return RiskDecision(
                        False,
                        f"{len(open_after)} open positions exceeds max {limits.max_open_positions}",
                        checks,
                    )
            checks.append("position")

            # daily loss
            if limits.max_daily_loss_inr and st.day_realized_pnl <= -abs(limits.max_daily_loss_inr):
                return RiskDecision(
                    False,
                    f"daily realized loss ₹{st.day_realized_pnl:,.0f} hit limit "
                    f"₹{-abs(limits.max_daily_loss_inr):,.0f}",
                    checks,
                )
            checks.append("daily_loss")

            return RiskDecision(True, None, checks)

    # --- post-decision bookkeeping ----------------------------------

    def record_submitted(self, deployment_id: str, order: OrderRequest, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            st = self._state(deployment_id)
            st.order_times.append(now)
            st.orders_today += 1
            st.recent.append((_fingerprint(order), now))

    def record_rejected(self, deployment_id: str, reason: str) -> None:
        with self._lock:
            self._state(deployment_id).last_reject = reason

    def record_fill(
        self, deployment_id: str, tradingsymbol: str, transaction_type: str, quantity: int
    ) -> None:
        signed = int(quantity) if transaction_type.upper() == "BUY" else -int(quantity)
        with self._lock:
            st = self._state(deployment_id)
            st.positions[tradingsymbol] = st.positions.get(tradingsymbol, 0) + signed
            if st.positions[tradingsymbol] == 0:
                st.positions.pop(tradingsymbol, None)

    def record_realized_pnl(self, deployment_id: str, delta_inr: float) -> None:
        with self._lock:
            self._state(deployment_id).day_realized_pnl += float(delta_inr)

    def sync_positions(self, deployment_id: str, positions: dict[str, int]) -> None:
        with self._lock:
            self._state(deployment_id).positions = {s: q for s, q in positions.items() if q}

    # --- monitoring ------------------------------------------------

    def snapshot(self, deployment_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            def one(st: _DeploymentRisk) -> dict[str, Any]:
                st.roll_day_if_needed()
                nowt = time.time()
                return {
                    "killed": st.killed,
                    "orders_today": st.orders_today,
                    "orders_last_minute": sum(1 for t in st.order_times if nowt - t < 60.0),
                    "open_positions": dict(st.positions),
                    "day_realized_pnl": round(st.day_realized_pnl, 2),
                    "last_reject": st.last_reject,
                }

            if deployment_id is not None:
                return {"global_kill": self._global_kill, **one(self._state(deployment_id))}
            return {
                "global_kill": self._global_kill,
                "deployments": {d: one(st) for d, st in self._by_deployment.items()},
            }

    def reset(self) -> None:  # test hook
        with self._lock:
            self._by_deployment.clear()
            self._global_kill = False


RISK = RiskEngine()

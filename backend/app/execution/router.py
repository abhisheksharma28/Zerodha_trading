"""Routes an order intent from a running strategy to the correct execution
path for its deployment's mode. This is the only place in the codebase that
is allowed to hold a live KiteClient reference for order placement — see
app.execution.guard for the invariants this depends on.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.brokers.base import BrokerClient, OrderRequest
from app.brokers.zerodha.order_builder import build_order_payload
from app.config import get_settings
from app.core.logging import get_logger
from app.execution import guard
from app.execution.paper_executor import PaperExecutor
from app.execution.sim_executor import SimulationExecutor
from app.live.latency import (
    LATENCY,
    STAGE_BROKER_RTT,
    STAGE_ORDER_DISPATCH,
    STAGE_ORDER_PREP,
    STAGE_RISK,
)
from app.live.risk import RISK, RiskLimits
from app.models.deployment import Deployment
from app.models.enums import AuditAction, ChangeEntityType, OrderStatus, TradingMode
from app.models.order import Order

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    order: Order
    broker_order_id: str | None


class OrderRouter:
    """Constructed once per running deployment by the deployment worker.
    `broker_client` is only ever non-None for a LIVE-mode router — a
    SIMULATION/PAPER router is constructed without one, so even a bug that
    calls the wrong method has no broker connection to misuse.
    """

    def __init__(
        self,
        db: Session,
        deployment: Deployment,
        broker_client: BrokerClient | None = None,
    ) -> None:
        self.db = db
        self.deployment = deployment
        self._broker_client = broker_client
        self._paper_executor = PaperExecutor(db)
        self._sim_executor = SimulationExecutor(db)

        if deployment.mode == TradingMode.LIVE and broker_client is None:
            raise RuntimeError(
                "OrderRouter constructed for a LIVE deployment without a "
                "broker_client — refusing to proceed rather than silently "
                "no-op or downgrade to simulation."
            )
        if deployment.mode != TradingMode.LIVE and broker_client is not None:
            # Structural safety: a non-LIVE router should never even be
            # holding a broker client capable of placing real orders.
            raise RuntimeError(
                f"OrderRouter for {deployment.mode.value} mode must not be "
                "constructed with a broker_client."
            )

    def submit(self, order_request: OrderRequest) -> ExecutionResult:
        logger.info(
            "order_intent",
            deployment_id=str(self.deployment.id),
            mode=self.deployment.mode.value,
            tradingsymbol=order_request.tradingsymbol,
            transaction_type=order_request.transaction_type,
            quantity=order_request.quantity,
        )

        # --- pre-trade risk (in-memory, measured). Runs for every mode so
        # PAPER/SIMULATION stay a faithful rehearsal of LIVE risk behaviour.
        deployment_id = str(self.deployment.id)
        limits = RiskLimits.from_settings(
            get_settings(), (self.deployment.config or {}).get("risk")
        )
        with LATENCY.span(STAGE_RISK):
            decision = RISK.evaluate(deployment_id, order_request, limits)
        if not decision.approved:
            return self._record_rejected(order_request, decision.reason or "risk check failed")
        RISK.record_submitted(deployment_id, order_request)

        if self.deployment.mode == TradingMode.LIVE:
            return self._execute_live(order_request)

        with LATENCY.span(STAGE_ORDER_DISPATCH):
            if self.deployment.mode == TradingMode.PAPER:
                guard.assert_mode_matches_deployment(self.deployment, TradingMode.PAPER)
                result = self._paper_executor.execute(self.deployment, order_request)
            elif self.deployment.mode == TradingMode.SIMULATION:
                guard.assert_mode_matches_deployment(self.deployment, TradingMode.SIMULATION)
                result = self._sim_executor.execute(self.deployment, order_request)
            else:
                raise RuntimeError(f"Unhandled deployment mode: {self.deployment.mode}")

        # PAPER/SIMULATION fill instantly — reflect it in the risk engine's
        # in-memory position book so subsequent position caps are accurate.
        if result.order.status == OrderStatus.COMPLETE:
            RISK.record_fill(
                deployment_id,
                order_request.tradingsymbol,
                order_request.transaction_type,
                int(order_request.quantity),
            )
        return result

    def _execute_live(self, order_request: OrderRequest) -> ExecutionResult:
        # Re-checked here, immediately before the broker call, even though
        # the deployment worker also checks this on every loop iteration —
        # see app.execution.guard module docstring for why this must never
        # be trusted from an earlier check alone.
        guard.assert_live_trading_authorized(self.db, str(self.deployment.id))
        assert self._broker_client is not None  # enforced in __init__

        with LATENCY.span(STAGE_ORDER_PREP):
            # Validate the payload shape (esp. market protection) even though
            # the broker client also builds it — fail before making the
            # network call, not after.
            build_order_payload(order_request)

            order_row = Order(
                mode=TradingMode.LIVE,
                deployment_id=self.deployment.id,
                tradingsymbol=order_request.tradingsymbol,
                exchange=order_request.exchange,
                transaction_type=order_request.transaction_type,
                order_type=order_request.order_type,
                product=order_request.product,
                variety=order_request.variety,
                quantity=order_request.quantity,
                price=order_request.price,
                trigger_price=order_request.trigger_price,
                market_protection=order_request.market_protection,
                raw_request=order_request.__dict__,
            )
            self.db.add(order_row)
            self.db.flush()

        # T7 -> T8: EXTERNAL latency (Kite + network). Tracked separately so
        # the UI never blames our engine for the broker round-trip.
        with LATENCY.span(STAGE_BROKER_RTT):
            result = self._broker_client.place_order(order_request)

        order_row.broker_order_id = result.broker_order_id
        order_row.raw_response = result.raw_response
        order_row.status = OrderStatus.OPEN  # confirmed via postback/reconciliation, not assumed COMPLETE
        self.db.commit()

        logger.info(
            "live_order_placed",
            deployment_id=str(self.deployment.id),
            broker_order_id=result.broker_order_id,
        )
        return ExecutionResult(order=order_row, broker_order_id=result.broker_order_id)

    def _record_rejected(self, order_request: OrderRequest, reason: str) -> ExecutionResult:
        """A risk breach: persist a REJECTED order + audit, and return it so
        the deployment keeps running rather than erroring out."""
        deployment_id = str(self.deployment.id)
        RISK.record_rejected(deployment_id, reason)
        order_row = Order(
            mode=self.deployment.mode,
            deployment_id=self.deployment.id,
            tradingsymbol=order_request.tradingsymbol,
            exchange=order_request.exchange,
            transaction_type=order_request.transaction_type,
            order_type=order_request.order_type,
            product=order_request.product,
            variety=order_request.variety,
            quantity=order_request.quantity,
            price=order_request.price,
            trigger_price=order_request.trigger_price,
            market_protection=order_request.market_protection,
            status=OrderStatus.REJECTED,
            status_message=f"risk: {reason}"[:1000],
            raw_request=order_request.__dict__,
            placed_at=datetime.now(UTC),
        )
        self.db.add(order_row)
        self.db.flush()
        record_audit(
            self.db,
            action=AuditAction.ORDER_REJECTED,
            entity_type=ChangeEntityType.DEPLOYMENT,
            entity_id=self.deployment.id,
            mode=self.deployment.mode,
            summary=(
                f"Risk engine rejected {order_request.transaction_type} "
                f"{order_request.quantity} {order_request.tradingsymbol}: {reason}"
            ),
            after={"order_id": str(order_row.id), "reason": reason},
            actor="risk-engine",
        )
        logger.warning(
            "order_rejected_by_risk",
            deployment_id=deployment_id,
            tradingsymbol=order_request.tradingsymbol,
            reason=reason,
        )
        return ExecutionResult(order=order_row, broker_order_id=None)

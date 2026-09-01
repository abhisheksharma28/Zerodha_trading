"""Simulation-mode executor.

Simulation is the lightest-weight of the three deployable modes: it exists
for testing strategy *logic* (does it fire the signals you expect) against
recent/live data without caring about realistic fill mechanics at all —
paper mode is the one that should be trusted for "would this have made
money". Like PaperExecutor, this class has no reference to a BrokerClient
and structurally cannot place a real order.
"""

from sqlalchemy.orm import Session

from app.brokers.base import OrderRequest
from app.models.deployment import Deployment
from app.models.enums import OrderStatus, TradingMode
from app.models.order import Order


class SimulationExecutor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, deployment: Deployment, order_request: OrderRequest):
        from app.execution.router import ExecutionResult  # local import avoids a cycle

        order_row = Order(
            mode=TradingMode.SIMULATION,
            deployment_id=deployment.id,
            tradingsymbol=order_request.tradingsymbol,
            exchange=order_request.exchange,
            transaction_type=order_request.transaction_type,
            order_type=order_request.order_type,
            product=order_request.product,
            variety=order_request.variety,
            quantity=order_request.quantity,
            price=order_request.price,
            trigger_price=order_request.trigger_price,
            status=OrderStatus.COMPLETE,  # instant, idealized fill at requested price
            raw_request=order_request.__dict__,
        )
        self.db.add(order_row)
        self.db.commit()
        return ExecutionResult(order=order_row, broker_order_id=None)

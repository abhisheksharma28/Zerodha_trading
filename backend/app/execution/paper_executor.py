"""Paper trading executor.

Paper mode uses real (or near-real-time) market prices to simulate fills but
NEVER calls a broker order-placement endpoint — it has no reference to a
BrokerClient at all (see OrderRouter.__init__), so there is no method on this
class capable of sending a real order even by mistake. This is intentionally
a stub for now: realistic fill modelling (slippage, partial fills against
depth) is a follow-up milestone, not part of the initial scaffold.
"""

from sqlalchemy.orm import Session

from app.brokers.base import OrderRequest
from app.models.deployment import Deployment
from app.models.enums import OrderStatus, TradingMode
from app.models.order import Order


class PaperExecutor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(self, deployment: Deployment, order_request: OrderRequest):
        from app.execution.router import ExecutionResult  # local import avoids a cycle

        order_row = Order(
            mode=TradingMode.PAPER,
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
            status=OrderStatus.COMPLETE,  # TODO: model realistic fill timing/slippage
            raw_request=order_request.__dict__,
        )
        self.db.add(order_row)
        self.db.commit()
        return ExecutionResult(order=order_row, broker_order_id=None)

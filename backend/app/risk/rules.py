"""Pre-trade risk checks, independent of and in addition to a strategy's own
position sizing. Every one of these runs inside app.execution.router before
an order reaches a broker call of any kind (including PAPER mode's simulated
fill, so paper trading stays a faithful rehearsal of live risk behaviour).
"""

from dataclasses import dataclass

from app.brokers.base import OrderRequest
from app.config import Settings
from app.core.exceptions import RiskLimitExceededError


@dataclass
class RiskContext:
    orders_today: int
    orders_this_minute: int


def check_order_risk(order: OrderRequest, ctx: RiskContext, settings: Settings) -> None:
    if ctx.orders_today >= settings.risk_max_orders_per_day:
        raise RiskLimitExceededError(
            f"Daily order limit reached ({settings.risk_max_orders_per_day})."
        )
    if ctx.orders_this_minute >= settings.risk_max_orders_per_minute:
        raise RiskLimitExceededError(
            f"Per-minute order limit reached ({settings.risk_max_orders_per_minute})."
        )
    if order.price is not None:
        notional = order.price * order.quantity
        if notional > settings.risk_max_live_order_value_inr:
            raise RiskLimitExceededError(
                f"Order notional ₹{notional:,.2f} exceeds configured limit "
                f"₹{settings.risk_max_live_order_value_inr:,.2f}."
            )

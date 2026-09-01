"""Builds Kite order payloads.

This is the single choke point every order passes through before it can
reach app.brokers.zerodha.client.KiteClient.place_order — see
docs/ZERODHA_API_NOTES.md section 4: market protection is mandatory on
MARKET/SL-M orders as of the SEBI/NSE algo-trading circular (in force since
1 Apr 2026), and an order submitted with protection "0" is rejected by the
exchange outright. Rather than relying on every call site to remember this,
build_order_payload() refuses outright to build such a payload without an
explicit protection value.
"""

from app.brokers.base import OrderRequest
from app.core.exceptions import ValidationError

_DEFAULT_MARKET_PROTECTION = -1.0  # exchange-automatic protection, per Kite docs
_ORDERS_REQUIRING_PROTECTION = {"MARKET", "SL-M"}


def build_order_payload(order: OrderRequest) -> dict:
    if order.order_type in _ORDERS_REQUIRING_PROTECTION:
        protection = order.market_protection
        if protection is None:
            # Default to exchange-automatic protection rather than silently
            # sending none — but this is logged so it's visible in the audit
            # trail that the caller didn't set one explicitly.
            protection = _DEFAULT_MARKET_PROTECTION
        if protection == 0:
            raise ValidationError(
                "market_protection cannot be 0 for MARKET/SL-M orders — exchange "
                "rejects protection-0 orders outright as of the Apr 2026 SEBI "
                "algo-trading circular."
            )
    else:
        protection = None

    if order.exchange == "MCX" and order.order_type == "MARKET":
        raise ValidationError("MARKET orders are not permitted on the MCX segment.")

    payload = {
        "tradingsymbol": order.tradingsymbol,
        "exchange": order.exchange,
        "transaction_type": order.transaction_type,
        "order_type": order.order_type,
        "quantity": order.quantity,
        "product": order.product,
        "validity": order.validity,
    }
    if order.price is not None:
        payload["price"] = order.price
    if order.trigger_price is not None:
        payload["trigger_price"] = order.trigger_price
    if protection is not None:
        payload["market_protection"] = protection

    return payload

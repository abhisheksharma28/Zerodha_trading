import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import OrderStatus, OrderTransactionType, OrderType, ProductType, TradingMode


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mode: TradingMode
    deployment_id: uuid.UUID | None
    backtest_id: uuid.UUID | None
    broker_order_id: str | None
    tradingsymbol: str
    exchange: str
    transaction_type: OrderTransactionType
    order_type: OrderType
    product: ProductType
    variety: str
    quantity: int
    price: float | None
    trigger_price: float | None
    status: OrderStatus
    status_message: str | None
    placed_at: datetime | None
    created_at: datetime


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    mode: TradingMode
    fill_price: float
    fill_quantity: int
    fill_time: datetime

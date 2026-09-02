"""Reconciler: broker order book -> OMS -> Order row + Trade + risk fill."""

from __future__ import annotations

import uuid

from app.live.oms import FILLED, OMS_ENGINE
from app.live.reconciler import reconcile
from app.live.risk import RISK
from app.models.deployment import Deployment
from app.models.enums import DeploymentStatus, OrderStatus, OrderType, ProductType, TradingMode
from app.models.enums import OrderTransactionType as Txn
from app.models.order import Order, Trade
from app.models.strategy import Strategy, StrategyVersion


class _FakeBroker:
    def __init__(self, orders):
        self._orders = orders

    def get_orders(self):
        return self._orders


def _live_order_row(db) -> Order:
    strategy = Strategy(name=f"s-{uuid.uuid4()}")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id, version_number=1,
        source_code="x", parameters={},
    )
    db.add(version)
    db.flush()
    dep = Deployment(
        strategy_version_id=version.id, name="rec", mode=TradingMode.LIVE,
        status=DeploymentStatus.RUNNING, instrument_universe=["NSE:INFY"], config={},
        live_trading_confirmed=True,
    )
    db.add(dep)
    db.flush()
    row = Order(
        mode=TradingMode.LIVE, deployment_id=dep.id, tradingsymbol="INFY", exchange="NSE",
        transaction_type=Txn.BUY, order_type=OrderType.MARKET, product=ProductType.MIS,
        quantity=10, status=OrderStatus.OPEN, broker_order_id="BR-100",
    )
    db.add(row)
    db.flush()
    return row


def test_reconcile_settles_a_fill(db):
    OMS_ENGINE.reset()
    RISK.reset()
    row = _live_order_row(db)
    OMS_ENGINE.register(str(row.id), deployment_id=str(row.deployment_id),
                        tradingsymbol="INFY", exchange="NSE", side="BUY", quantity=10)
    OMS_ENGINE.mark_submitted(str(row.id), "BR-100")

    broker = _FakeBroker([
        {"order_id": "BR-100", "status": "COMPLETE", "filled_quantity": 10,
         "average_price": 1499.75, "tradingsymbol": "INFY", "transaction_type": "BUY", "quantity": 10},
    ])
    result = reconcile(db, broker)
    db.flush()

    assert result["settled"] == 1
    assert OMS_ENGINE.get(str(row.id)).state == FILLED
    db.refresh(row)
    assert row.status == OrderStatus.COMPLETE
    assert db.query(Trade).filter(Trade.order_id == row.id).count() == 1
    assert row.raw_response["oms"]["state"] == "FILLED"
    assert RISK.snapshot(str(row.deployment_id))["open_positions"] == {"INFY": 10}
    OMS_ENGINE.reset()
    RISK.reset()


def test_reconcile_noop_when_nothing_open(db):
    OMS_ENGINE.reset()
    assert reconcile(db, _FakeBroker([])) == {"checked": 0, "settled": 0}

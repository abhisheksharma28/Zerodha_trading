"""OrderRouter runs the risk engine before every execution path. A breach
records a REJECTED order and returns it — the deployment is NOT errored."""

from __future__ import annotations

import uuid

from app.brokers.base import OrderRequest
from app.execution.router import OrderRouter
from app.live.risk import RISK
from app.models.deployment import Deployment
from app.models.enums import DeploymentStatus, OrderStatus, TradingMode
from app.models.strategy import Strategy, StrategyVersion


def _sim_deployment(db, config: dict | None = None) -> Deployment:
    strategy = Strategy(name=f"s-{uuid.uuid4()}")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version_number=1,
        source_code="from app.strategies.base import BaseStrategy\nclass Strategy(BaseStrategy):\n    def on_bar(self, b): pass\n",
        parameters={},
    )
    db.add(version)
    db.flush()
    dep = Deployment(
        strategy_version_id=version.id,
        name="risk-test",
        mode=TradingMode.SIMULATION,
        status=DeploymentStatus.RUNNING,
        instrument_universe=["NSE:INFY"],
        config=config or {},
    )
    db.add(dep)
    db.flush()
    return dep


def _order(qty=10, price=None):
    return OrderRequest(
        tradingsymbol="INFY", exchange="NSE", transaction_type="BUY",
        order_type="MARKET" if price is None else "LIMIT", quantity=qty, product="MIS", price=price,
    )


def test_clean_order_fills_and_updates_risk_positions(db):
    RISK.reset()
    dep = _sim_deployment(db)
    router = OrderRouter(db, dep)

    res = router.submit(_order(qty=25))
    assert res.order.status == OrderStatus.COMPLETE
    snap = RISK.snapshot(str(dep.id))
    assert snap["open_positions"] == {"INFY": 25}
    assert snap["orders_today"] == 1
    RISK.reset()


def test_over_notional_order_is_rejected_not_executed(db):
    RISK.reset()
    dep = _sim_deployment(db, {"risk": {"max_order_notional_inr": 10_000}})
    router = OrderRouter(db, dep)

    res = router.submit(_order(qty=100, price=500))  # ₹50,000 > 10,000
    assert res.order.status == OrderStatus.REJECTED
    assert "risk:" in (res.order.status_message or "")
    assert res.broker_order_id is None
    # deployment untouched, risk engine saw no fill
    assert dep.status == DeploymentStatus.RUNNING
    assert RISK.snapshot(str(dep.id))["open_positions"] == {}
    RISK.reset()


def test_kill_switch_blocks_execution(db):
    RISK.reset()
    dep = _sim_deployment(db)
    RISK.kill(str(dep.id))
    router = OrderRouter(db, dep)

    res = router.submit(_order())
    assert res.order.status == OrderStatus.REJECTED
    assert "kill switch" in (res.order.status_message or "")
    RISK.reset()

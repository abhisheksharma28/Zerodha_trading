"""Automatic circuit breakers: stale-data + feed-down trip/clear, override,
and the router refusing orders while halted."""

from __future__ import annotations

import uuid

from app.brokers.base import OrderRequest
from app.execution.router import OrderRouter
from app.live.circuit_breakers import BREAKERS as GLOBAL_BREAKERS
from app.live.circuit_breakers import REASON_DATA_STALE, REASON_FEED_DOWN, CircuitBreakers
from app.live.risk import RISK
from app.models.deployment import Deployment
from app.models.enums import DeploymentStatus, OrderStatus, TradingMode
from app.models.strategy import Strategy, StrategyVersion


def test_feed_down_trips_and_clears():
    cb = CircuitBreakers()
    cb.observe(feed_connected=False, seconds_since_tick=None, stale_threshold=15, market_open=True)
    assert cb.halted
    assert any(r["reason"] == REASON_FEED_DOWN for r in cb.snapshot()["reasons"])

    cb.observe(feed_connected=True, seconds_since_tick=1.0, stale_threshold=15, market_open=True)
    assert not cb.halted


def test_stale_data_only_trips_during_market_hours():
    cb = CircuitBreakers()
    cb.observe(feed_connected=True, seconds_since_tick=99.0, stale_threshold=15, market_open=False)
    assert not cb.halted  # market closed -> a quiet feed is expected

    cb.observe(feed_connected=True, seconds_since_tick=99.0, stale_threshold=15, market_open=True)
    assert cb.halted
    assert any(r["reason"] == REASON_DATA_STALE for r in cb.snapshot()["reasons"])


def test_force_clear_override():
    cb = CircuitBreakers()
    cb.observe(feed_connected=False, seconds_since_tick=None, stale_threshold=15, market_open=True)
    assert cb.halted
    cb.force_clear_all()
    assert not cb.halted
    assert cb.snapshot()["override_active"] is True
    # a fresh trip re-arms it
    cb.trip("x", "y")
    assert cb.halted


def _sim_deployment(db) -> Deployment:
    s = Strategy(name=f"s-{uuid.uuid4()}")
    db.add(s)
    db.flush()
    v = StrategyVersion(strategy_id=s.id, version_number=1, source_code="x", parameters={})
    db.add(v)
    db.flush()
    d = Deployment(
        strategy_version_id=v.id, name="cb", mode=TradingMode.SIMULATION,
        status=DeploymentStatus.RUNNING, instrument_universe=["NSE:INFY"], config={},
    )
    db.add(d)
    db.flush()
    return d


def test_router_rejects_orders_while_halted(db):
    RISK.reset()
    GLOBAL_BREAKERS.reset()
    dep = _sim_deployment(db)
    GLOBAL_BREAKERS.trip(REASON_DATA_STALE, "no ticks for 40s")
    router = OrderRouter(db, dep)

    res = router.submit(
        OrderRequest(tradingsymbol="INFY", exchange="NSE", transaction_type="BUY",
                     order_type="MARKET", quantity=1, product="MIS")
    )
    assert res.order.status == OrderStatus.REJECTED
    assert "circuit breaker" in (res.order.status_message or "")

    GLOBAL_BREAKERS.reset()
    RISK.reset()

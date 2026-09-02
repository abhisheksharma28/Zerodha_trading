"""Pre-trade risk engine: every limit, the duplicate guard, the kill switch."""

from __future__ import annotations

import pytest

from app.brokers.base import OrderRequest
from app.live.risk import RiskEngine, RiskLimits


def _order(qty: int = 10, side: str = "BUY", price: float | None = None, sym: str = "INFY") -> OrderRequest:
    return OrderRequest(
        tradingsymbol=sym,
        exchange="NSE",
        transaction_type=side,
        order_type="MARKET" if price is None else "LIMIT",
        quantity=qty,
        product="MIS",
        price=price,
    )


@pytest.fixture
def eng() -> RiskEngine:
    return RiskEngine()


def test_clean_order_is_approved(eng):
    d = eng.evaluate("dep1", _order(), RiskLimits())
    assert d.approved and d.reason is None
    assert "duplicate" in d.checks and "position" in d.checks


def test_max_order_quantity(eng):
    limits = RiskLimits(max_order_quantity=100)
    assert eng.evaluate("d", _order(qty=100), limits).approved
    d = eng.evaluate("d", _order(qty=101), limits)
    assert not d.approved and "qty 101" in d.reason


def test_max_order_notional(eng):
    limits = RiskLimits(max_order_notional_inr=50_000)
    assert eng.evaluate("d", _order(qty=10, price=5_000), limits).approved   # 50k exactly
    d = eng.evaluate("d", _order(qty=11, price=5_000), limits)               # 55k
    assert not d.approved and "notional" in d.reason


def test_order_rate_per_second(eng):
    limits = RiskLimits(max_orders_per_second=3, max_orders_per_minute=999, max_orders_per_day=999)
    now = 1_000_000.0
    # distinct orders (different qty) so the duplicate guard doesn't fire first
    for i in range(3):
        assert eng.evaluate("d", _order(qty=10 + i), limits, now=now).approved
        eng.record_submitted("d", _order(qty=10 + i), now=now)
    d = eng.evaluate("d", _order(qty=99), limits, now=now)
    assert not d.approved and "/s" in d.reason
    # a second later the rate window has cleared
    assert eng.evaluate("d", _order(qty=99), limits, now=now + 1.1).approved


def test_daily_order_cap(eng):
    limits = RiskLimits(max_orders_per_day=2, max_orders_per_second=99, max_orders_per_minute=99)
    for _ in range(2):
        eng.record_submitted("d", _order())
    d = eng.evaluate("d", _order(), limits)
    assert not d.approved and "daily order count" in d.reason


def test_duplicate_guard(eng):
    limits = RiskLimits(duplicate_window_seconds=2.0)
    now = 5_000.0
    eng.record_submitted("d", _order(qty=10, sym="INFY"), now=now)
    d = eng.evaluate("d", _order(qty=10, sym="INFY"), limits, now=now + 0.5)
    assert not d.approved and "duplicate" in d.reason
    # different qty is not a duplicate
    assert eng.evaluate("d", _order(qty=11, sym="INFY"), limits, now=now + 0.5).approved
    # same order after the window is fine
    assert eng.evaluate("d", _order(qty=10, sym="INFY"), limits, now=now + 3.0).approved


def test_position_cap_per_instrument(eng):
    limits = RiskLimits(max_position_qty_per_instrument=50)
    eng.record_fill("d", "INFY", "BUY", 45)
    assert eng.evaluate("d", _order(qty=5, side="BUY", sym="INFY"), limits).approved      # -> 50
    d = eng.evaluate("d", _order(qty=6, side="BUY", sym="INFY"), limits)                  # -> 51
    assert not d.approved and "projected position" in d.reason
    # selling to reduce is always fine
    assert eng.evaluate("d", _order(qty=40, side="SELL", sym="INFY"), limits).approved


def test_max_open_positions(eng):
    limits = RiskLimits(max_open_positions=2)
    eng.record_fill("d", "AAA", "BUY", 1)
    eng.record_fill("d", "BBB", "BUY", 1)
    d = eng.evaluate("d", _order(qty=1, sym="CCC"), limits)
    assert not d.approved and "open positions" in d.reason
    # adding to an existing position is fine
    assert eng.evaluate("d", _order(qty=1, sym="AAA"), limits).approved


def test_daily_loss_halt(eng):
    limits = RiskLimits(max_daily_loss_inr=10_000)
    eng.record_realized_pnl("d", -9_999)
    assert eng.evaluate("d", _order(), limits).approved
    eng.record_realized_pnl("d", -2)
    d = eng.evaluate("d", _order(), limits)
    assert not d.approved and "daily realized loss" in d.reason


def test_kill_switch_deployment_and_global(eng):
    eng.kill("d")
    assert not eng.evaluate("d", _order(), RiskLimits()).approved
    assert eng.evaluate("other", _order(), RiskLimits()).approved
    eng.resume("d")
    assert eng.evaluate("d", _order(), RiskLimits()).approved

    eng.kill_all()
    assert not eng.evaluate("d", _order(), RiskLimits()).approved
    assert not eng.evaluate("anything", _order(), RiskLimits()).approved
    eng.resume_all()
    assert eng.evaluate("d", _order(), RiskLimits()).approved


def test_snapshot_shape(eng):
    eng.record_submitted("d", _order())
    eng.record_fill("d", "INFY", "BUY", 10)
    eng.record_realized_pnl("d", -250.5)
    snap = eng.snapshot("d")
    assert snap["orders_today"] == 1
    assert snap["open_positions"] == {"INFY": 10}
    assert snap["day_realized_pnl"] == -250.5
    assert snap["global_kill"] is False


def test_from_settings_merges_overrides():
    from app.config import get_settings

    lim = RiskLimits.from_settings(get_settings(), {"max_open_positions": 3, "bogus": 1})
    assert lim.max_open_positions == 3
    assert lim.max_orders_per_day == get_settings().risk_max_orders_per_day

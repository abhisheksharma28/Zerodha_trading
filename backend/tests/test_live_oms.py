"""OMS state machine + broker-status folding + timeout adoption."""

from __future__ import annotations

import pytest

from app.live.oms import (
    FAILED,
    FILLED,
    OMS,
    OPEN,
    PARTIALLY_FILLED,
    REJECTED,
    SUBMITTED,
    InvalidTransition,
)


def _reg(oms: OMS, iid="o1", sym="INFY", side="BUY", qty=10):
    return oms.register(iid, deployment_id="d1", tradingsymbol=sym, exchange="NSE", side=side, quantity=qty)


def test_happy_path_transitions():
    oms = OMS()
    o = _reg(oms)
    assert o.state == "CREATED"
    oms.mark_submitted("o1", "BR-1")
    assert o.state == SUBMITTED and o.broker_order_id == "BR-1"
    assert o.submitted_at is not None

    done = oms.apply_broker_status(
        {"order_id": "BR-1", "status": "OPEN", "filled_quantity": 0}
    )
    assert done is None and o.state == OPEN

    done = oms.apply_broker_status(
        {"order_id": "BR-1", "status": "COMPLETE", "filled_quantity": 10, "average_price": 1500.5}
    )
    assert done is o
    assert o.state == FILLED and o.filled_qty == 10 and o.avg_fill_price == 1500.5
    assert o.terminal
    assert o.as_dict()["latency_ms"]["submit_to_fill"] is not None


def test_partial_then_full_fill():
    oms = OMS()
    o = _reg(oms, qty=100)
    oms.mark_submitted("o1", "BR-2")
    oms.apply_broker_status({"order_id": "BR-2", "status": "OPEN", "filled_quantity": 40, "average_price": 10})
    assert o.state == PARTIALLY_FILLED and o.filled_qty == 40
    done = oms.apply_broker_status(
        {"order_id": "BR-2", "status": "COMPLETE", "filled_quantity": 100, "average_price": 10.2}
    )
    assert done is o and o.state == FILLED


def test_broker_rejection_is_terminal_with_reason():
    oms = OMS()
    o = _reg(oms)
    oms.mark_submitted("o1", "BR-3")
    done = oms.apply_broker_status(
        {"order_id": "BR-3", "status": "REJECTED", "status_message": "insufficient funds"}
    )
    assert done is o and o.state == REJECTED
    assert o.reject_reason == "insufficient funds"


def test_invalid_transition_rejected():
    oms = OMS()
    o = _reg(oms)
    o.state = FILLED  # terminal
    with pytest.raises(InvalidTransition):
        oms._transition(o, OPEN)


def test_in_flight_fingerprint_blocks_double_submit():
    oms = OMS()
    _reg(oms, iid="o1")
    oms.mark_submitted("o1", "BR-4")
    assert oms.in_flight_fingerprint("d1", "INFY", "BUY", 10) is True
    assert oms.in_flight_fingerprint("d1", "INFY", "SELL", 10) is False


def test_adopt_unclaimed_after_timeout():
    oms = OMS()
    o = _reg(oms, qty=25)
    oms.mark_submitted("o1", None)  # broker call timed out, no id
    assert o.broker_order_id is None

    oms.adopt_unclaimed(
        [
            {"order_id": "BR-9", "tradingsymbol": "INFY", "transaction_type": "BUY", "quantity": 25},
            {"order_id": "BR-8", "tradingsymbol": "RELIANCE", "transaction_type": "BUY", "quantity": 25},
        ]
    )
    assert o.broker_order_id == "BR-9"
    # and it can now be settled
    done = oms.apply_broker_status(
        {"order_id": "BR-9", "status": "COMPLETE", "filled_quantity": 25, "average_price": 1500}
    )
    assert done is o and o.state == FILLED


def test_mark_failed():
    oms = OMS()
    o = _reg(oms)
    oms.mark_failed("o1", "network unreachable")
    assert o.state == FAILED and o.reject_reason == "network unreachable"


def test_snapshot_counts():
    oms = OMS()
    _reg(oms, iid="a")
    _reg(oms, iid="b")
    oms.mark_submitted("b", "BR-b")
    snap = oms.snapshot()
    assert snap["counts"]["CREATED"] == 1
    assert snap["counts"]["SUBMITTED"] == 1
    assert snap["open"] == 2

"""Baskets deployed into the paper account — deploy, status, rebalance,
undeploy, and the cadence gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.baskets import paper
from app.baskets.spec import parse_spec
from app.config import get_settings
from app.core.exceptions import ValidationError
from app.models.basket import Basket
from app.models.instrument import Instrument
from app.paper_account import engine, pricing
from app.strategies.base import Bar

_PX = {"NSE:AAA": 100.0, "NSE:BBB": 50.0}


@pytest.fixture(autouse=True)
def _fixed_prices(monkeypatch):
    def _quotes(_db, _settings, refs):
        return {r["ref"]: pricing.Quote(r["ref"], _PX.get(r["ref"]), None) for r in refs}

    monkeypatch.setattr(pricing, "quotes", _quotes)


def _instrument(db, token, sym):
    db.add(Instrument(
        instrument_token=token, tradingsymbol=sym, name=sym, exchange="NSE",
        segment="NSE", instrument_type="EQ", lot_size=1, tick_size=0.05, active=True,
    ))


def _bars(sym):
    day0 = datetime(2024, 1, 1)
    return [
        Bar(timestamp=(day0 + timedelta(days=i)).isoformat(), open=_PX[f"NSE:{sym}"],
            high=_PX[f"NSE:{sym}"], low=_PX[f"NSE:{sym}"], close=_PX[f"NSE:{sym}"],
            volume=1000, instrument=sym)
        for i in range(40)
    ]


_SPEC = {
    "sleeves": [
        {"id": "a", "name": "A", "weight_pct": 60, "weighting": "equal",
         "members": ["AAA"], "rule": {"type": "none"}},
        {"id": "b", "name": "B", "weight_pct": 40, "weighting": "equal",
         "members": ["BBB"], "rule": {"type": "none"}},
    ]
}


@pytest.fixture()
def _hist(monkeypatch):
    monkeypatch.setattr(
        paper, "_history",
        lambda *_a, **_k: ({"AAA": _bars("AAA"), "BBB": _bars("BBB")}, []),
    )


def _make_basket(db, **over) -> Basket:
    b = Basket(
        name=over.get("name", "test basket"),
        benchmark="NIFTY 50",
        rebalance_frequency=over.get("rebalance_frequency", "monthly"),
        drift_band_pct=over.get("drift_band_pct", 3.0),
        capital=over.get("capital", 200_000),
        spec=parse_spec(_SPEC).to_dict(),
        status="draft",
    )
    db.add(b)
    db.flush()
    return b


def test_deploy_buys_the_basket_and_status_reports_weights(db, _hist):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    b = _make_basket(db)

    out = paper.deploy(db, s, str(b.id))
    assert out["applied"] is True
    assert out["orders_placed"] == 2
    assert db.get(Basket, b.id).status == "deployed"

    st = paper.status(db, s, str(b.id))
    held = {h["symbol"]: h for h in st["holdings"]}
    assert set(held) == {"AAA", "BBB"}
    # 60 / 40 target on ~200k, minus charges/slippage -> close to target
    assert held["AAA"]["weight"] == pytest.approx(0.60, abs=0.03)
    assert held["BBB"]["weight"] == pytest.approx(0.40, abs=0.03)
    assert st["rebalance_due"] is False  # just rebalanced


def test_rebalance_is_cadence_gated_unless_forced(db, _hist):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    b = _make_basket(db)
    paper.deploy(db, s, str(b.id))

    # same month -> not due
    r = paper.rebalance(db, s, str(b.id))
    assert r.get("skipped") is True

    # forced always runs
    r2 = paper.rebalance(db, s, str(b.id), force=True)
    assert r2["applied"] is True

    # pretend the last rebalance was last quarter -> now due
    bb = db.get(Basket, b.id)
    bb.last_rebalanced_at = datetime.now(UTC) - timedelta(days=95)
    db.flush()
    r3 = paper.rebalance(db, s, str(b.id))
    assert r3["applied"] is True


def test_undeploy_liquidates_and_resets_status(db, _hist):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    b = _make_basket(db)
    paper.deploy(db, s, str(b.id))

    out = paper.undeploy(db, s, str(b.id), liquidate=True)
    assert out["positions_sold"] == 2
    assert out["status"] == "draft"

    st = paper.status(db, s, str(b.id))
    assert all(h["qty"] == 0 for h in st["holdings"]) or st["holdings"] == []


def test_is_due_boundaries(db):
    b = _make_basket(db, rebalance_frequency="monthly")
    now = datetime(2026, 3, 10, tzinfo=UTC)
    b.last_rebalanced_at = datetime(2026, 3, 1, tzinfo=UTC)
    assert paper._is_due(b, now.astimezone(paper.IST)) is False
    b.last_rebalanced_at = datetime(2026, 2, 27, tzinfo=UTC)
    assert paper._is_due(b, now.astimezone(paper.IST)) is True
    b.last_rebalanced_at = None
    assert paper._is_due(b, now.astimezone(paper.IST)) is True


def test_tick_all_rebalances_only_due_deployed_baskets(db, _hist, monkeypatch):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    b = _make_basket(db)
    paper.deploy(db, s, str(b.id))
    db.get(Basket, b.id).last_rebalanced_at = datetime.now(UTC) - timedelta(days=40)
    db.flush()

    n = paper.tick_all(db, s)
    assert n == 1


def test_deploy_stamps_cadence_clock_so_a_racing_tick_does_not_double_buy(db, _hist):
    """deploy() must set last_rebalanced_at before committing 'deployed', so
    a scheduler tick landing in the gap sees a not-due basket."""
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    b = _make_basket(db)
    paper.deploy(db, s, str(b.id))

    bb = db.get(Basket, b.id)
    assert bb.last_rebalanced_at is not None
    assert paper._is_due(bb, datetime.now(paper.IST)) is False

    # a tick right now is a no-op, so holdings do not double
    from app.paper_account.engine import get_or_create_account
    acct = get_or_create_account(db)
    net_before, _ = paper._tagged_state(db, acct.id, b.id)
    paper.tick_all(db, s)
    net_after, _ = paper._tagged_state(db, acct.id, b.id)
    assert net_after == net_before

    # a forced rebalance still runs (require_due is only for the auto path)
    r = paper.rebalance(db, s, str(b.id), force=True)
    assert r["applied"] is True


def test_deploy_preview_reports_unit_cost_and_affordable_units(db, _hist):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    acct = engine.get_or_create_account(db)
    acct.cash = 1_500.0
    db.flush()
    b = _make_basket(db, capital=200_000)

    prev = paper.deploy_preview(db, s, str(b.id))
    # min capital to hold at target weights: AAA at 60% needs 100/0.60 = 166.7,
    # rounded up to the nearest 100 -> 200 (NOT the 150 sum of one share each)
    assert prev["unit_cost"] == pytest.approx(200.0)
    assert prev["n_members"] == 2 and prev["n_priced"] == 2
    assert prev["est_holdings"] == 2
    assert prev["max_units"] == 7                       # 1500 // 200
    assert prev["available_cash"] == pytest.approx(1_500.0)


def test_deploy_with_capital_override_persists_and_is_funded_checked(db, _hist):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    acct = engine.get_or_create_account(db)
    acct.cash = 1_000.0
    db.flush()
    b = _make_basket(db, capital=200_000)

    # 4 units * 150 = 600 -> affordable, overrides the 200k stored capital
    out = paper.deploy(db, s, str(b.id), capital=600.0)
    assert out["applied"] is True
    assert db.get(Basket, b.id).capital == pytest.approx(600.0)

    # a size the account can't fund is refused
    b2 = _make_basket(db, name="too big", capital=200_000)
    with pytest.raises(ValidationError, match="only"):
        paper.deploy(db, s, str(b2.id), capital=5_000.0)


def test_deploy_refuses_when_the_basket_capital_exceeds_free_cash(db, _hist):
    s = get_settings()
    _instrument(db, "1001", "AAA")
    _instrument(db, "1002", "BBB")
    db.flush()
    acct = engine.get_or_create_account(db)
    acct.cash = 50_000.0                       # far less than the 200k basket capital
    db.flush()

    b = _make_basket(db, capital=200_000)
    with pytest.raises(ValidationError, match="only"):
        paper.deploy(db, s, str(b.id))
    assert db.get(Basket, b.id).status == "draft"   # not left half-deployed

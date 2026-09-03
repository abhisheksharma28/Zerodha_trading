"""Paper trading account: order fills, position/holding math, cash book."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.models.instrument import Instrument
from app.paper_account import engine, pricing
from app.paper_account.engine import OrderRequest
from app.paper_account.service import summary


@pytest.fixture(autouse=True)
def _fixed_prices(monkeypatch):
    """Deterministic quotes so fills don't need a broker session."""
    px: dict[str, float] = {
        "NSE:RELIANCE": 1300.0, "NSE:TCS": 3800.0,
        "NFO:NIFTY24FEBFUT": 22000.0, "NFO:NIFTY2420022000CE": 120.0,
    }

    def _quotes(_db, _settings, refs):
        return {r["ref"]: pricing.Quote(r["ref"], px.get(r["ref"]), None) for r in refs}

    monkeypatch.setattr(pricing, "quotes", _quotes)
    return px


def _mk(db, **kw):
    db.add(Instrument(
        instrument_token=kw["instrument_token"], tradingsymbol=kw["tradingsymbol"],
        name=kw.get("name"), exchange=kw["exchange"], segment=kw.get("segment", kw["exchange"]),
        instrument_type=kw.get("instrument_type", "EQ"), lot_size=kw.get("lot_size"),
        tick_size=kw.get("tick_size", 0.05), expiry=kw.get("expiry"), strike=kw.get("strike"),
        active=True,
    ))


def test_cnc_buy_then_sell_books_pnl(db, monkeypatch, _fixed_prices):
    s = get_settings()
    _mk(db, instrument_token="738561", tradingsymbol="RELIANCE", exchange="NSE")
    db.flush()

    o = engine.place_order(db, s, OrderRequest("NSE", "RELIANCE", "BUY", 10, product="CNC"))
    assert o.status == "COMPLETE" and o.avg_fill_price == 1300.0
    hold = engine.get_or_create_account(db)
    assert float(hold.cash) < 1_000_000  # value + charges debited

    _fixed_prices["NSE:RELIANCE"] = 1350.0
    o2 = engine.place_order(db, s, OrderRequest("NSE", "RELIANCE", "SELL", 10, product="CNC"))
    assert o2.status == "COMPLETE"
    acct = engine.get_or_create_account(db)
    # ~ +500 gross minus round-trip charges
    assert 400 < float(acct.realized_pnl) < 500
    sm = summary(db, s)
    assert sm["counts"]["holdings"] == 0


def test_mis_position_blocks_margin_not_full_value(db, _fixed_prices):
    s = get_settings()
    _mk(db, instrument_token="738561", tradingsymbol="RELIANCE", exchange="NSE")
    db.flush()
    start = float(engine.get_or_create_account(db).cash)
    engine.place_order(db, s, OrderRequest("NSE", "RELIANCE", "BUY", 100, product="MIS"))
    acct = engine.get_or_create_account(db)
    spent = start - float(acct.cash)
    # MIS ~20% of 130,000 + charges, nowhere near the full 130,000
    assert 20_000 < spent < 40_000
    sm = summary(db, s)
    assert sm["counts"]["positions"] == 1
    assert sm["funds"]["used_margin"] > 20_000


def test_fno_short_sell_opens_a_position(db, _fixed_prices):
    s = get_settings()
    _mk(db, instrument_token="9101", tradingsymbol="NIFTY24FEBFUT", exchange="NFO",
        segment="NFO-FUT", instrument_type="FUT", lot_size=50)
    db.flush()
    o = engine.place_order(db, s, OrderRequest("NFO", "NIFTY24FEBFUT", "SELL", 50, product="NRML"))
    assert o.status == "COMPLETE"
    pos = engine.get_or_create_account(db)  # just to touch the account
    assert pos is not None
    sm = summary(db, s)
    p = sm and s and engine.get_or_create_account(db)
    assert p is not None
    from app.paper_account.service import positions
    rows = positions(db, s)
    assert rows and rows[0]["net_qty"] == -50 and rows[0]["product"] == "NRML"


def test_reset_wipes_and_restores_opening_balance(db, _fixed_prices):
    s = get_settings()
    _mk(db, instrument_token="738561", tradingsymbol="RELIANCE", exchange="NSE")
    db.flush()
    engine.place_order(db, s, OrderRequest("NSE", "RELIANCE", "BUY", 5, product="CNC"))
    engine.reset_account(db)
    acct = engine.get_or_create_account(db)
    assert float(acct.cash) == float(acct.opening_balance)
    assert float(acct.realized_pnl) == 0.0
    assert summary(db, s)["counts"] == {"positions": 0, "holdings": 0, "open_orders": 0}


def test_insufficient_funds_rejects(db, _fixed_prices):
    s = get_settings()
    _mk(db, instrument_token="500325", tradingsymbol="TCS", exchange="NSE")
    db.flush()
    o = engine.place_order(db, s, OrderRequest("NSE", "TCS", "BUY", 100_000, product="CNC"))
    assert o.status == "REJECTED" and "Insufficient" in (o.status_message or "")


def test_limit_order_rests_then_fills_on_tick(db, _fixed_prices):
    s = get_settings()
    _mk(db, instrument_token="738561", tradingsymbol="RELIANCE", exchange="NSE")
    db.flush()
    o = engine.place_order(db, s, OrderRequest(
        "NSE", "RELIANCE", "BUY", 10, order_type="LIMIT", price=1250.0, product="CNC"))
    assert o.status == "OPEN"
    from app.paper_account import scheduler
    assert scheduler._fill_resting(db, s) == 0  # LTP 1300 > limit 1250, no fill
    _fixed_prices["NSE:RELIANCE"] = 1240.0
    assert scheduler._fill_resting(db, s) == 1
    db.refresh(o)
    assert o.status == "COMPLETE"


# --------------------------------------------------------------------------
# strategies deployed inside the paper account
# --------------------------------------------------------------------------

def test_deploy_strategy_lifecycle_and_tagged_fills(db, monkeypatch, _fixed_prices):
    from app.paper_account import strategies as strat
    from app.paper_account.service import strategy_runs
    from app.strategies.base import StrategyContext
    from app.strategies.library import get_template

    _mk(db, instrument_token="738561", tradingsymbol="RELIANCE", exchange="NSE")
    db.flush()
    s = get_settings()

    # a fake template: buys 3 on the first bar, does nothing after
    class _Fake:
        SLUG = "fake-buy"
        NAME = "Fake buy-once"
        CATEGORY = "Test"
        MIN_INSTRUMENTS = 1
        MAX_INSTRUMENTS = 1
        SUPPORTED_TIMEFRAMES = ("1d",)

        def __init__(self, ctx: StrategyContext):
            self.ctx = ctx
            self._done = False

        def on_start(self):
            pass

        def on_bar(self, bar):
            # buy to a target of 3 whenever flat (real templates re-signal)
            if self.ctx.positions.get("RELIANCE", 0) != 0:
                return
            from app.brokers.base import OrderRequest as BrokerOrderRequest
            self.ctx.submit_order(BrokerOrderRequest(
                tradingsymbol="RELIANCE", exchange="NSE", transaction_type="BUY",
                order_type="MARKET", quantity=3, product="CNC",
            ))

        @classmethod
        def resolve_params(cls, supplied):
            return dict(supplied)

    monkeypatch.setattr(strat, "get_by_slug", lambda slug: _Fake if slug == "fake-buy" else get_template(slug))
    monkeypatch.setattr(strat, "_client", lambda *_a, **_k: object())

    from app.strategies.base import Bar
    bars = [Bar(timestamp=f"2026-08-{d:02d}", open=1300, high=1310, low=1290, close=1300 + d,
                volume=1000, instrument="RELIANCE") for d in range(1, 6)]
    monkeypatch.setattr(strat, "_bars_for", lambda *_a, **_k: bars)

    run = strat.create_run(db, slug="fake-buy", name="t1", instruments=["NSE:RELIANCE"],
                           timeframe="1d", product="CNC", params={})
    assert run.status == "ACTIVE"
    placed = strat.tick_run(db, s, run)
    assert placed == 1

    rows = strategy_runs(db)
    assert rows and rows[0]["orders_placed"] == 1 and rows[0]["open_exposure"] == {"RELIANCE": 3}

    # stop with flatten -> a SELL 3 is placed
    strat.set_status(db, s, str(run.id), "STOPPED")
    from app.paper_account.service import positions as _positions
    assert _positions(db, s) == []  # net flat


def test_create_run_rejects_bad_input(db, _fixed_prices):
    from app.core.exceptions import ValidationError
    from app.paper_account import strategies as strat

    with pytest.raises(ValidationError):
        strat.create_run(db, slug="does-not-exist", name="x", instruments=["NSE:INFY"],
                         timeframe="1d", product="CNC", params={})

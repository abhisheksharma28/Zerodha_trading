"""Auto-trade bridge: the Trading Ideas engine feeding the paper account
when the algo toggle is on."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import get_settings
from app.core.exceptions import ValidationError
from app.models.instrument import Instrument
from app.models.market_scanner import ScanRecommendation
from app.paper_account import algo, pricing
from app.paper_account.engine import get_or_create_account

IST = algo.IST


@pytest.fixture(autouse=True)
def _fixed_prices(monkeypatch):
    px: dict[str, float] = {
        "NSE:INFY": 1500.0, "NSE:WIPRO": 400.0,
        "NFO:BANKNIFTY24DEC52000CE": 300.0, "NFO:BANKNIFTY24DEC52500CE": 150.0,
    }

    def _quotes(_db, _settings, refs):
        return {r["ref"]: pricing.Quote(r["ref"], px.get(r["ref"]), None) for r in refs}

    monkeypatch.setattr(pricing, "quotes", _quotes)
    return px


def _inst(db, **kw):
    db.add(Instrument(
        instrument_token=kw["instrument_token"], tradingsymbol=kw["tradingsymbol"],
        name=kw.get("name"), exchange=kw["exchange"], segment=kw.get("segment", kw["exchange"]),
        instrument_type=kw.get("instrument_type", "EQ"), lot_size=kw.get("lot_size"),
        tick_size=0.05, expiry=kw.get("expiry"), strike=kw.get("strike"), active=True,
    ))


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _rec(db, **over) -> ScanRecommendation:
    base: dict = {
        "exchange": "NSE", "tradingsymbol": "INFY", "instrument_token": "408065", "segment": "NSE",
        "name": "Infosys", "asset_class": "EQUITY", "horizon": "SWING",
        "trade_style": "EQUITY_DELIVERY", "direction": "LONG",
        "setup_type": "Break-of-structure continuation", "setup_tags": ["bos"],
        "ref_price": 1500.0, "entry": 1500.0, "entry_type": "MARKET", "stop_loss": 1440.0,
        "target_1": 1620.0, "target_2": 1680.0, "rr": 2.0, "atr": 25.0,
        "confidence": 80.0, "bias_score": 55.0, "score_detail": {"grade": "A"},
        "factors": [], "status": "LIVE", "trading_day": _today(),
    }
    base.update(over)
    r = ScanRecommendation(**base)
    db.add(r)
    db.flush()
    return r


def _before_cutoff() -> datetime:
    return datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def test_config_defaults_to_off_with_the_ab_preset(db):
    cfg = algo.get_config(db)
    assert cfg.enabled is False
    assert cfg.min_grade == "B" and float(cfg.pct_per_trade) == 2.0
    assert cfg.max_open_auto == 8 and cfg.cutoff_ist == "14:45"


def test_set_config_validates(db):
    with pytest.raises(ValidationError):
        algo.set_config(db, {"min_grade": "Z"})
    with pytest.raises(ValidationError):
        algo.set_config(db, {"cutoff_ist": "9am"})
    cfg = algo.set_config(db, {"enabled": True, "min_grade": "a", "pct_per_trade": 3.5})
    assert cfg.enabled is True and cfg.min_grade == "A" and float(cfg.pct_per_trade) == 3.5


# --------------------------------------------------------------------------
# taking trades
# --------------------------------------------------------------------------

def test_disabled_takes_nothing(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _rec(db)
    db.flush()
    out = algo.run_once(db, s, now=_before_cutoff())
    assert out["enabled"] is False and out["taken"] == []


def test_enabled_takes_a_qualifying_idea_with_a_protective_stop(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    rec = _rec(db)
    db.flush()
    algo.set_config(db, {"enabled": True, "min_grade": "B", "pct_per_trade": 5.0})

    out = algo.run_once(db, s, now=_before_cutoff())
    assert len(out["taken"]) == 1
    t = out["taken"][0]
    assert t["symbol"] == "INFY" and t["qty"] >= 1 and t["stop_child"] is True

    from app.models.paper_account import PaperOrder

    acct = get_or_create_account(db)
    tags = {o.tag: o.status for o in db.query(PaperOrder).filter(
        PaperOrder.account_id == acct.id).all()}
    assert tags.get(f"algo:{rec.id}") == "COMPLETE"
    assert tags.get(f"algo:{rec.id}:sl") == "OPEN"


def test_grade_filter_skips_weak_ideas(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _rec(db, confidence=50.0, score_detail={"grade": "C"})
    db.flush()
    algo.set_config(db, {"enabled": True, "min_grade": "A"})
    out = algo.run_once(db, s, now=_before_cutoff())
    assert out["taken"] == []


def test_type_filter_skips_options_when_disallowed(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _rec(db, trade_style="OPTION", option_overlay={
        "structure": "bull_call_spread", "lot_size": 15, "net_debit": 40.0,
        "legs": [{"tradingsymbol": "X", "side": "BUY"}, {"tradingsymbol": "Y", "side": "SELL"}],
    })
    db.flush()
    algo.set_config(db, {"enabled": True, "allow_options": False})
    out = algo.run_once(db, s, now=_before_cutoff())
    assert out["taken"] == []


def test_cutoff_time_blocks_new_trades(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _rec(db)
    db.flush()
    algo.set_config(db, {"enabled": True, "cutoff_ist": "14:45"})
    late = datetime.now(IST).replace(hour=15, minute=0, second=0, microsecond=0)
    out = algo.run_once(db, s, now=late)
    assert out["taken"] == [] and "cut-off" in out["skipped"]


def test_max_open_auto_cap(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _inst(db, instrument_token="225537", tradingsymbol="WIPRO", exchange="NSE")
    _rec(db, tradingsymbol="INFY", instrument_token="408065")
    _rec(db, tradingsymbol="WIPRO", instrument_token="225537", entry=400.0,
         stop_loss=384.0, target_1=440.0)
    db.flush()
    algo.set_config(db, {"enabled": True, "min_grade": "B", "max_open_auto": 1,
                         "pct_per_trade": 5.0})
    out = algo.run_once(db, s, now=_before_cutoff())
    assert len(out["taken"]) == 1  # second idea blocked by the cap


def test_idempotent_within_the_day(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _rec(db)
    db.flush()
    algo.set_config(db, {"enabled": True, "min_grade": "B", "pct_per_trade": 5.0})
    first = algo.run_once(db, s, now=_before_cutoff())
    second = algo.run_once(db, s, now=_before_cutoff())
    assert len(first["taken"]) == 1 and second["taken"] == []


def test_daily_loss_stop_halts_and_persists(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    _rec(db)
    db.flush()
    cfg = algo.set_config(db, {"enabled": True, "daily_loss_stop_pct": 5.0})

    # simulate a big prior algo loss today by hand-booking a tagged trade
    from app.models.paper_account import PaperOrder, PaperTrade

    acct = get_or_create_account(db)
    o = PaperOrder(account_id=acct.id, exchange="NSE", tradingsymbol="INFY",
                   instrument_token="408065", segment="NSE", asset_class="EQUITY",
                   side="SELL", order_type="MARKET", product="MIS", quantity=1,
                   status="COMPLETE", filled_qty=1, tag="algo:prior",
                   placed_at=datetime.now(UTC), filled_at=datetime.now(UTC))
    db.add(o)
    db.flush()
    db.add(PaperTrade(account_id=acct.id, order_id=o.id, exchange="NSE", tradingsymbol="INFY",
                      asset_class="EQUITY", product="MIS", side="SELL", quantity=1,
                      price=1.0, value=1.0, charges=0.0, realized_pnl=-120_000.0,
                      traded_at=datetime.now(UTC)))
    db.commit()

    out = algo.run_once(db, s, now=_before_cutoff())
    assert out["taken"] == [] and "loss stop" in out["skipped"]
    db.refresh(cfg)
    assert cfg.halted_day == _today() and cfg.halted_reason


# --------------------------------------------------------------------------
# managing open auto positions
# --------------------------------------------------------------------------

def test_manage_squares_off_when_the_idea_expires(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    rec = _rec(db)
    db.flush()
    algo.set_config(db, {"enabled": True, "min_grade": "B", "pct_per_trade": 5.0})
    algo.run_once(db, s, now=_before_cutoff())

    acct = get_or_create_account(db)
    assert str(rec.id) in algo._open_algo_rec_ids(db, acct.id)

    rec.status = "EXPIRED"
    rec.outcome = "TARGET"
    db.commit()

    out = algo.manage(db, s)
    assert out["closed"] and out["closed"][0]["symbol"] == "INFY"
    assert algo._open_algo_rec_ids(db, acct.id) == set()

    from app.models.paper_account import PaperOrder

    sl = db.query(PaperOrder).filter(PaperOrder.tag == f"algo:{rec.id}:sl").one()
    assert sl.status == "CANCELLED"


def test_status_view_shape(db):
    s = get_settings()
    st = algo.status(db, s)
    assert set(st) >= {"config", "open_auto_positions", "max_open_auto",
                       "today_realized_pnl", "halted"}
    assert st["config"]["enabled"] is False


# --------------------------------------------------------------------------
# "Add to paper" — take one idea into the portfolio on request
# --------------------------------------------------------------------------

def test_take_idea_places_a_persistent_delivery_position(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    rec = _rec(db, trade_style="EQUITY_DELIVERY", direction="LONG")
    db.flush()

    res = algo.take_idea(db, s, str(rec.id), pct=5.0)
    assert res["ok"] and res["symbol"] == "INFY" and res["product"] == "CNC"
    assert "paper portfolio" in res["message"]

    from app.models.paper_account import PaperHolding, PaperOrder

    acct = get_or_create_account(db)
    holds = db.query(PaperHolding).filter(PaperHolding.account_id == acct.id).all()
    assert holds and holds[0].tradingsymbol == "INFY" and holds[0].qty >= 1
    tags = [o.tag for o in db.query(PaperOrder).filter(PaperOrder.account_id == acct.id).all()]
    assert any(t == f"idea:{rec.id}" for t in tags)


def test_take_idea_respects_an_explicit_quantity(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    rec = _rec(db)
    db.flush()
    res = algo.take_idea(db, s, str(rec.id), quantity=7)
    assert res["ok"] and res["qty"] == 7


def test_take_idea_unknown_recommendation_raises(db):
    s = get_settings()
    with pytest.raises(ValidationError):
        algo.take_idea(db, s, "00000000-0000-0000-0000-000000000000")


def test_taken_rec_ids_lists_button_and_auto_positions(db):
    s = get_settings()
    _inst(db, instrument_token="408065", tradingsymbol="INFY", exchange="NSE")
    rec = _rec(db)
    db.flush()
    assert algo.taken_rec_ids(db) == set()
    algo.take_idea(db, s, str(rec.id), quantity=3)
    assert str(rec.id) in algo.taken_rec_ids(db)


def test_account_is_a_stable_singleton(db):
    # many lookups (mimicking the parallel first-load requests) never fork it
    ids = {str(get_or_create_account(db).id) for _ in range(6)}
    assert len(ids) == 1
    from app.models.paper_account import PaperAccount

    assert db.query(PaperAccount).count() == 1

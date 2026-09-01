"""Instrument master: sync from Zerodha dumps + ranked search."""

from __future__ import annotations

import pytest

from app.models.instrument import Instrument
from app.services import instrument_service

_NSE_CSV_V1 = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE
408065,1594,INFY,INFOSYS,0,,0,0.05,1,EQ,NSE,NSE
5633,22,INFIBEAM,INFIBEAM AVENUES,0,,0,0.05,1,EQ,NSE,NSE
256265,1001,NIFTY 50,NIFTY 50,0,,0,0.05,0,EQ,INDICES,NSE
260105,1016,NIFTY BANK,NIFTY BANK,0,,0,0.05,0,EQ,INDICES,NSE
"""

# same as V1 but INFIBEAM has been removed (delisted)
_NSE_CSV_V2 = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE
408065,1594,INFY,INFOSYS,0,,0,0.05,1,EQ,NSE,NSE
256265,1001,NIFTY 50,NIFTY 50,0,,0,0.05,0,EQ,INDICES,NSE
260105,1016,NIFTY BANK,NIFTY BANK,0,,0,0.05,0,EQ,INDICES,NSE
"""

_NFO_CSV = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
11111,111,NIFTY25JAN26FUT,NIFTY,0,2026-01-29,0,0.05,25,FUT,NFO-FUT,NFO
22222,222,NIFTY25JAN2624000CE,NIFTY,0,2026-01-29,24000,0.05,25,CE,NFO-OPT,NFO
33333,333,NIFTY25JAN2624000PE,NIFTY,0,2026-01-29,24000,0.05,25,PE,NFO-OPT,NFO
44444,444,NIFTY25JAN2624500CE,NIFTY,0,2026-01-29,24500,0.05,25,CE,NFO-OPT,NFO
55555,555,NIFTY25FEB26FUT,NIFTY,0,2026-02-26,0,0.05,25,FUT,NFO-FUT,NFO
66666,666,RELIANCE25JAN26FUT,RELIANCE,0,2026-01-29,0,0.05,250,FUT,NFO-FUT,NFO
"""


@pytest.fixture()
def dumps(monkeypatch):
    store = {"NSE": _NSE_CSV_V1, "NFO": _NFO_CSV, "BSE": "instrument_token,exchange_token,"
             "tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,"
             "segment,exchange\n"}
    monkeypatch.setattr(instrument_service, "fetch_instrument_dump", lambda ex: store[ex.upper()])
    return store


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(Instrument).delete()
    db.commit()
    yield


def test_sync_creates_rows(db, dumps):
    result = instrument_service.sync(db, ["NSE", "NFO"])
    assert result["total"] == 5 + 6
    assert result["by_exchange"]["NSE"]["rows"] == 5
    assert db.query(Instrument).filter_by(exchange="NSE", tradingsymbol="RELIANCE").count() == 1
    fut = db.query(Instrument).filter_by(tradingsymbol="NIFTY25JAN26FUT").one()
    assert fut.instrument_type == "FUT" and fut.underlying == "NIFTY" and fut.lot_size == 25
    assert str(fut.expiry) == "2026-01-29"
    ce = db.query(Instrument).filter_by(tradingsymbol="NIFTY25JAN2624000CE").one()
    assert ce.instrument_type == "CE" and float(ce.strike) == 24000.0


def test_sync_is_idempotent_and_deactivates_missing(db, dumps):
    instrument_service.sync(db, ["NSE"])
    assert db.query(Instrument).filter_by(tradingsymbol="INFIBEAM", active=True).count() == 1

    dumps["NSE"] = _NSE_CSV_V2  # INFIBEAM delisted
    result = instrument_service.sync(db, ["NSE"])
    assert result["by_exchange"]["NSE"]["deactivated"] == 1
    infibeam = db.query(Instrument).filter_by(tradingsymbol="INFIBEAM").one()
    assert infibeam.active is False
    # unchanged rows still exactly one each (upsert, not duplicate insert)
    assert db.query(Instrument).filter_by(tradingsymbol="RELIANCE").count() == 1


def test_search_ranks_exact_then_prefix_then_name(db, dumps):
    instrument_service.sync(db, ["NSE"])
    hits = instrument_service.search(db, "INF")
    syms = [h.tradingsymbol for h in hits]
    # INFY (symbol prefix) and INFIBEAM (symbol prefix) both match; INFY is shorter
    assert syms[:2] == ["INFY", "INFIBEAM"]

    exact = instrument_service.search(db, "reliance")
    assert exact[0].tradingsymbol == "RELIANCE"

    by_name = instrument_service.search(db, "infosys")
    assert by_name and by_name[0].tradingsymbol == "INFY"


def test_search_groups_cash_before_derivatives(db, dumps):
    instrument_service.sync(db, ["NSE", "NFO"])
    hits = instrument_service.search(db, "NIFTY", limit=50)
    types = [h.instrument_type for h in hits]
    # the index (EQ) must rank above futures and options
    assert types[0] == "EQ"
    assert types.index("EQ") < types.index("FUT") <= types.index("CE")


def test_search_filters_by_instrument_type(db, dumps):
    instrument_service.sync(db, ["NFO"])
    only_ce = instrument_service.search(db, "NIFTY", instrument_type="CE", limit=50)
    assert only_ce and all(h.instrument_type == "CE" for h in only_ce)


def test_derivative_helpers(db, dumps):
    instrument_service.sync(db, ["NFO"])
    unders = instrument_service.underlyings(db)
    assert set(unders) == {"NIFTY", "RELIANCE"}

    exps = instrument_service.expiries(db, "NIFTY")
    assert exps == ["2026-01-29", "2026-02-26"]

    strikes = instrument_service.option_strikes(db, "NIFTY", "2026-01-29")
    assert [(s["strike"], s["option_type"]) for s in strikes] == [
        (24000.0, "CE"), (24000.0, "PE"), (24500.0, "CE"),
    ]


def test_get_by_token_and_by_symbol(db, dumps):
    instrument_service.sync(db, ["NSE"])
    assert instrument_service.get_by_token(db, "738561").tradingsymbol == "RELIANCE"
    assert instrument_service.get(db, "NSE", "infy").name == "INFOSYS"
    assert instrument_service.get_by_token(db, "does-not-exist") is None

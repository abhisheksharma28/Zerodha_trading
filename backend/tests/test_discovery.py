"""Portfolio Alpha Discovery Engine — Phase 1 (universe + ingest + normalise)."""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.discovery import ingest, normalize, universe
from app.discovery import service as disc_service


def _monthly(start: date, months: int, m_ret: float, p0: float = 100.0) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    p = p0
    y, mo = start.year, start.month
    for _ in range(months):
        out.append((date(y, mo, 1), round(p, 4)))
        p *= 1.0 + m_ret
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return out


def test_universe_is_curated_and_multi_asset():
    inst = universe.all_instruments()
    assert len(inst) >= 15
    assert len({u.symbol for u in inst}) == len(inst)  # unique
    classes = {u.asset_class for u in inst}
    assert {"EQUITY", "BOND", "COMMODITY", "REIT"} <= classes
    assert universe.get("spy") is not None and universe.get("SPY").currency == "USD"


def test_ingest_writes_bars_and_assigns_tiers(db):
    series = {
        "SPY": _monthly(date(2010, 1, 1), 190, 0.008),   # ~15.8y -> Tier A
        "AGG": _monthly(date(2016, 1, 1), 96, 0.003),     # ~7.9y -> Tier B
        "IWM": _monthly(date(2019, 1, 1), 44, 0.006),     # ~3.6y -> Tier C
        "HYG": _monthly(date(2022, 6, 1), 20, 0.003),     # <2y -> Tier D
    }
    res = ingest.ingest_prices(db, series=series, source="test", bar_interval="1month")
    assert res["instruments"] == 4 and res["bars"] == 190 + 96 + 44 + 20

    st = disc_service.universe_status(db)
    by = {i["symbol"]: i for i in st["instruments"]}
    assert by["SPY"]["tier"] == "A" and by["SPY"]["n_points"] == 190
    assert by["AGG"]["tier"] == "B"
    assert by["IWM"]["tier"] == "C"
    assert by["HYG"]["tier"] == "D"
    assert st["by_tier"].get("A") == 1
    assert st["n_ingested"] == 4


def test_ingest_is_idempotent(db):
    series = {"SPY": _monthly(date(2015, 1, 1), 60, 0.005)}
    ingest.ingest_prices(db, series=series, source="test")
    ingest.ingest_prices(db, series=series, source="test")  # re-run
    st = disc_service.universe_status(db)
    assert next(i for i in st["instruments"] if i["symbol"] == "SPY")["n_points"] == 60


def test_returns_frame_aligns_common_history_and_computes_returns(db):
    series = {
        "SPY": _monthly(date(2018, 1, 1), 48, 0.01),
        "TLT": _monthly(date(2019, 1, 1), 60, 0.002),   # starts a year later
    }
    ingest.ingest_prices(db, series=series, source="test")
    fr = normalize.returns_frame(db, ["SPY", "TLT"], currency="USD")
    # common history starts 2019-01, SPY has 36 months there -> 35 returns
    assert len(fr["dates"]) == 36
    assert len(fr["returns"]["SPY"]) == 35
    assert math.isclose(fr["returns"]["SPY"][0], 0.01, abs_tol=1e-6)
    assert math.isclose(fr["returns"]["TLT"][0], 0.002, abs_tol=1e-6)

    frl = normalize.returns_frame(db, ["SPY", "TLT"], currency="USD", kind="log")
    assert math.isclose(frl["returns"]["SPY"][0], math.log(1.01), abs_tol=1e-6)


def test_returns_frame_fx_adjusts_to_inr(db):
    series = {"SPY": _monthly(date(2020, 1, 1), 13, 0.0)}  # flat in USD
    # rupee depreciates 1%/month -> the INR-denominated SPY return is +1%/month
    fx = {"USD/INR": _monthly(date(2020, 1, 1), 13, 0.01, p0=75.0)}
    ingest.ingest_prices(db, series=series, fx=fx, source="test")

    usd = normalize.returns_frame(db, ["SPY"], currency="USD")
    inr = normalize.returns_frame(db, ["SPY"], currency="INR")
    assert inr["fx_adjusted"] is True
    assert math.isclose(usd["returns"]["SPY"][0], 0.0, abs_tol=1e-9)
    assert math.isclose(inr["returns"]["SPY"][0], 0.01, abs_tol=1e-6)


def test_twelvedata_series_parses_the_rest_response(monkeypatch):
    from app.discovery import providers

    class _Resp:
        def raise_for_status(self): ...
        def json(self):
            return {"status": "ok", "values": [
                {"datetime": "2020-01-01", "close": "100.0"},
                {"datetime": "2020-02-01", "close": "105.5"},
                {"datetime": "2020-03-01", "close": "0"},   # dropped (<= 0)
            ]}

    class _Client:
        def get(self, url, params=None):
            assert params["symbol"] == "SPY" and params["apikey"] == "k"
            return _Resp()

    monkeypatch.setattr(providers, "_throttle", lambda: None)
    monkeypatch.setattr(providers, "get_settings", lambda: type(
        "S", (), {"twelvedata_api_key": "k", "twelvedata_api_base": "http://x"})())
    pts = providers.twelvedata_series("SPY", client=_Client())
    assert pts == [(date(2020, 1, 1), 100.0), (date(2020, 2, 1), 105.5)]


def test_twelvedata_series_raises_without_a_key(monkeypatch):
    from app.discovery import providers

    monkeypatch.setattr(providers, "get_settings", lambda: type(
        "S", (), {"twelvedata_api_key": "", "twelvedata_api_base": "http://x"})())
    with pytest.raises(RuntimeError, match="TWELVEDATA_API_KEY"):
        providers.twelvedata_series("SPY")


def test_parse_twelvedata_csv():
    text = (
        "datetime;open;high;low;close;volume\n"
        "2026-08-01;749.44;779.37;748.79;767.05;833955700\n"
        "2026-07-01;745;755.58;729.09;747.03;1064946100\n"
        "bad line here\n"
    )
    pts = ingest.parse_twelvedata_csv(text)
    assert pts == [(date(2026, 8, 1), 767.05), (date(2026, 7, 1), 747.03)]


def test_returns_frame_reports_missing_symbols(db):
    ingest.ingest_prices(db, series={"SPY": _monthly(date(2019, 1, 1), 40, 0.005)}, source="test")
    fr = normalize.returns_frame(db, ["SPY", "QQQ"], currency="USD")
    assert "QQQ" in fr["missing"] and "SPY" in fr["returns"]

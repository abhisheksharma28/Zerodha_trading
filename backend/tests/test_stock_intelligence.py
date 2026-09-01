"""Fundamentals provider abstraction + stock quick-look service."""

from __future__ import annotations

import pytest

from app.providers.fundamentals import get_fundamentals_provider
from app.providers.fundamentals.base import FundamentalDataProvider
from app.providers.fundamentals.indian_api import IndianApiFundamentalsProvider
from app.providers.fundamentals.null import NullFundamentalsProvider


class _S:
    def __init__(self, provider="none", key="", base=""):
        self.fundamentals_provider = provider
        self.fundamentals_api_key = key
        self.fundamentals_api_base = base


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    from app.providers.fundamentals import _build

    _build.cache_clear()
    yield
    _build.cache_clear()


def test_default_provider_is_null_and_reports_unavailable():
    p = get_fundamentals_provider(_S())
    assert isinstance(p, NullFundamentalsProvider)
    assert isinstance(p, FundamentalDataProvider)  # structural
    for meth in ("get_company_profile", "get_key_metrics", "get_financials",
                 "get_shareholding", "get_news"):
        r = getattr(p, meth)("INFY")
        assert r.available is False and r.source == "none" and r.data is None
        assert "FUNDAMENTALS_PROVIDER" in r.reason


def test_indianapi_selected_only_with_key():
    from app.providers.fundamentals.yfinance_provider import YFinanceFundamentalsProvider

    # indianapi without a key falls back to the free default, not to nothing
    assert isinstance(
        get_fundamentals_provider(_S("indianapi", "")), YFinanceFundamentalsProvider
    )
    p = get_fundamentals_provider(_S("indianapi", "k-123"))
    assert isinstance(p, IndianApiFundamentalsProvider)


def test_yfinance_is_the_default():
    from app.providers.fundamentals.yfinance_provider import YFinanceFundamentalsProvider

    assert isinstance(get_fundamentals_provider(_S("yfinance")), YFinanceFundamentalsProvider)
    assert isinstance(get_fundamentals_provider(_S("")), YFinanceFundamentalsProvider)


def test_indianapi_slices_the_blob(monkeypatch):
    import app.providers.fundamentals.indian_api as mod

    mod._cache.clear()
    blob = {
        "companyProfile": {"companyName": "Infosys Ltd", "sector": "IT"},
        "keyMetrics": {"pe": 24.8, "roe": 29.4},
    }

    class _Resp:
        status_code = 200

        def json(self):
            return blob

    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp())
    p = IndianApiFundamentalsProvider("k-123")
    prof = p.get_company_profile("INFY")
    assert prof.available is True and prof.data["companyName"] == "Infosys Ltd"
    km = p.get_key_metrics("INFY")
    assert km.data["pe"] == 24.8
    assert p.get_cash_flow("INFY").available is False  # not in blob -> graceful miss


def test_indianapi_network_failure_is_graceful(monkeypatch):
    import app.providers.fundamentals.indian_api as mod

    mod._cache.clear()

    def _boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(mod.httpx, "get", _boom)
    r = IndianApiFundamentalsProvider("k-123").get_company_profile("INFY")
    assert r.available is False and "unavailable" in r.reason


def test_quick_look_combines_instrument_and_quote(db, monkeypatch):
    from app.models.instrument import Instrument
    from app.services import broker_service, stock_service

    db.query(Instrument).delete()
    db.add(Instrument(
        instrument_token="408065", tradingsymbol="INFY", name="INFOSYS", exchange="NSE",
        segment="NSE", instrument_type="EQ", lot_size=1, tick_size=0.1, active=True,
    ))
    db.commit()

    class _Client:
        def get_quote(self, keys):
            return {"NSE:INFY": {"last_price": 1500.0, "volume": 999,
                                 "ohlc": {"open": 1490, "high": 1510, "low": 1480, "close": 1470.0}}}

    monkeypatch.setattr(broker_service, "build_authenticated_client", lambda d, s: _Client())
    out = stock_service.quick_look(db, _S(), "nse", "infy")
    assert out["symbol"] == "INFY"
    assert out["instrument"]["name"] == "INFOSYS"
    assert out["quote"]["available"] is True
    assert out["quote"]["ltp"] == 1500.0
    assert round(out["quote"]["change_pct"], 2) == round((1500 - 1470) / 1470 * 100, 2)
    assert out["fundamentals_provider"] == "none"
    assert out["profile"]["available"] is False

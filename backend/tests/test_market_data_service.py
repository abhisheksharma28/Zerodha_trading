"""Market overview: breadth / gainers / losers / sectors / signals from quotes."""

from __future__ import annotations

import pytest

from app.core.exceptions import BrokerNotConnectedError
from app.services import broker_service, market_data_service

_UNIVERSE = [
    ("AAA", "A Corp", "IT"),
    ("BBB", "B Corp", "IT"),
    ("CCC", "C Corp", "Bank"),
    ("DDD", "D Corp", "Bank"),
]

# ltp / prev-close / open / high / low / volume.  AAA +10%, BBB -5%, CCC 0%, DDD -10%.
_QUOTES = {
    "NSE:AAA": {"last_price": 110.0, "ohlc": {"open": 106, "high": 110.2, "low": 104, "close": 100.0},
                "volume": 1_000, "timestamp": "2026-09-01 15:30:00"},
    "NSE:BBB": {"last_price": 95.0, "ohlc": {"open": 99, "high": 100, "low": 94, "close": 100.0},
                "volume": 2_000, "timestamp": "2026-09-01 15:30:01"},
    "NSE:CCC": {"last_price": 100.0, "ohlc": {"open": 100, "high": 100.9, "low": 99.1, "close": 100.0},
                "volume": 50_000, "timestamp": "2026-09-01 15:29:59"},
    "NSE:DDD": {"last_price": 90.0, "ohlc": {"open": 92, "high": 96, "low": 89.8, "close": 100.0},
                "volume": 3_000, "timestamp": "2026-09-01 15:30:00"},
}


class _FakeClient:
    def get_quote(self, instruments):
        return {k: v for k, v in _QUOTES.items() if k in instruments}


@pytest.fixture(autouse=True)
def _no_overview_cache():
    market_data_service._overview_cache.clear()
    market_data_service._overview_refreshing.clear()
    yield
    market_data_service._overview_cache.clear()
    market_data_service._overview_refreshing.clear()


@pytest.fixture()
def wired(monkeypatch):
    monkeypatch.setattr(market_data_service, "UNIVERSES", {"t": _UNIVERSE})
    monkeypatch.setattr(market_data_service, "BROAD_INDICES", [])
    monkeypatch.setattr(market_data_service, "SECTOR_INDICES", [])
    monkeypatch.setattr(broker_service, "build_authenticated_client", lambda db, s: _FakeClient())


def test_overview_unavailable_without_broker(monkeypatch):
    def _raise(db, s):
        raise BrokerNotConnectedError("no session")

    monkeypatch.setattr(broker_service, "build_authenticated_client", _raise)
    out = market_data_service.market_overview(None, None, universe="t")
    assert out["available"] is False and "session" in out["reason"]


def test_breadth_gainers_losers(wired):
    out = market_data_service.market_overview(None, None, universe="t")
    assert out["available"] is True
    assert out["constituent_count"] == 4
    assert out["breadth"] == {
        "advances": 1, "declines": 2, "unchanged": 1, "total": 4, "ad_ratio": 0.5,
    }
    assert out["gainers"][0]["symbol"] == "AAA"
    assert out["gainers"][0]["change_pct"] == pytest.approx(10.0)
    assert out["losers"][0]["symbol"] == "DDD"  # -10%, worst
    assert out["losers"][0]["change_pct"] == pytest.approx(-10.0)


def test_sector_aggregation_sorted(wired):
    out = market_data_service.market_overview(None, None, universe="t")
    secs = {s["sector"]: s for s in out["sectors"]}
    assert secs["IT"]["avg_change_pct"] == pytest.approx(2.5)   # (+10 + -5) / 2
    assert secs["Bank"]["avg_change_pct"] == pytest.approx(-5.0)  # (0 + -10) / 2
    assert [s["sector"] for s in out["sectors"]] == ["IT", "Bank"]  # desc
    assert secs["IT"]["advances"] == 1 and secs["IT"]["declines"] == 1


def test_most_active_by_traded_value(wired):
    out = market_data_service.market_overview(None, None, universe="t")
    # CCC: 100 * 50_000 = 5,000,000 — far the largest
    assert out["most_active"][0]["symbol"] == "CCC"


def test_intraday_signals(wired):
    out = market_data_service.market_overview(None, None, universe="t")
    sig = out["signals"]
    assert "AAA" in sig["gap_up"]           # open 106 vs prev 100 = +6%
    assert "DDD" in sig["gap_down"]         # open 92 vs prev 100 = -8%
    assert "AAA" in sig["near_day_high"]    # ltp 110 vs high 111
    assert "DDD" in sig["near_day_low"]     # ltp 90 vs low 89.7


def test_heatmap_covers_every_constituent(wired):
    out = market_data_service.market_overview(None, None, universe="t")
    assert {h["symbol"] for h in out["heatmap"]} == {"AAA", "BBB", "CCC", "DDD"}
    assert out["heatmap"][0]["change_pct"] >= out["heatmap"][-1]["change_pct"]

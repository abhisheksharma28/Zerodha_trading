"""Market Insights briefing — assembly + narrative from mocked services."""

from __future__ import annotations

from app.insights import briefing


def _overview(**over):
    base = {
        "available": True,
        "indices": [
            {"symbol": "NIFTY 50", "ltp": 24000.0, "change_pct": 0.8},
            {"symbol": "NIFTY BANK", "ltp": 52000.0, "change_pct": 0.3},
            {"symbol": "INDIA VIX", "ltp": 11.2, "change_pct": -2.0},
        ],
        "breadth": {"advances": 140, "declines": 55, "unchanged": 5, "total": 200, "ad_ratio": 2.55},
        "gainers": [{"symbol": "BSE", "change_pct": 4.4}, {"symbol": "TITAGARH", "change_pct": 3.1}],
        "losers": [{"symbol": "XYZ", "change_pct": -2.2}],
        "most_active": [{"symbol": "RELIANCE", "change_pct": 0.5}],
        "sectors": [
            {"sector": "Financial Services", "count": 20, "advances": 16, "declines": 3, "avg_change_pct": 1.3},
            {"sector": "IT", "count": 10, "advances": 7, "declines": 2, "avg_change_pct": 0.6},
            {"sector": "Auto", "count": 8, "advances": 2, "declines": 6, "avg_change_pct": -0.9},
            {"sector": "Metal", "count": 6, "advances": 1, "declines": 5, "avg_change_pct": -1.4},
        ],
        "signals": {"gap_up": ["BSE"], "gap_down": [], "near_day_high": ["BSE"], "near_day_low": []},
    }
    base.update(over)
    return base


def test_briefing_assembles_all_sections(monkeypatch):
    monkeypatch.setattr(briefing, "market_overview", lambda *a, **k: _overview())
    monkeypatch.setattr(
        briefing, "_scanner_digest",
        lambda _db: {
            "available": True, "live": 30, "long": 24, "short": 6, "long_pct": 80.0,
            "top_sectors": [("Financial Services", 9), ("IT", 5)],
            "top_ideas": [{"symbol": "HDFCBANK", "direction": "LONG", "style": "EQUITY_DELIVERY",
                           "setup": "Break-of-structure", "grade": "A", "confidence": 82,
                           "entry": 1700, "stop": 1650, "target": 1800, "rr": 2.0}],
        },
    )
    monkeypatch.setattr(
        briefing, "_book_digest",
        lambda _db, _s: {
            "available": True, "net_worth": 1_050_000, "total_pnl": 50_000,
            "total_pnl_pct": 5.0, "day_pnl": 3_200, "available_margin": 400_000,
            "counts": {"positions": 2, "holdings": 6, "open_orders": 0},
            "movers": [{"symbol": "TCS", "day_change_pct": -6.1, "pnl_pct": -3.0}],
            "deployed_baskets": [{"id": "b1", "name": "All-Weather", "return_pct": 1.2, "rebalance_due": True}],
            "alerts": ["Basket “All-Weather” is due for a rebalance."],
        },
    )
    monkeypatch.setattr(briefing, "_seasonality_note", lambda: {
        "month": "September", "anchor": None,
        "historical_long_tilt": ["PSU BANK", "AUTO"], "historical_short_tilt": ["IT"],
        "verdict": "NO VALID EDGE FOUND", "caveat": "context only",
    })

    rep = briefing.build(None, None)
    assert rep["available"] is True
    assert rep["pulse"]["risk_tone"] == "risk-on"          # +0.8%, A/D 2.55, VIX 11
    assert rep["pulse"]["vol_regime"] == "calm"
    assert rep["sectors"]["leaders"][0]["sector"] == "Financial Services"
    assert rep["sectors"]["laggards"][0]["sector"] == "Metal"
    assert "risk-on" in rep["headline"]
    assert rep["scanner"]["long_pct"] == 80.0
    assert rep["book"]["total_pnl_pct"] == 5.0
    assert any("rebalance" in b for b in rep["bullets"])   # book alert surfaced
    assert rep["seasonality"]["month"] == "September"


def test_briefing_handles_no_market_data(monkeypatch):
    monkeypatch.setattr(
        briefing, "market_overview",
        lambda *a, **k: {"available": False, "reason": "broker offline"},
    )
    rep = briefing.build(None, None)
    assert rep["available"] is False and "broker offline" in rep["reason"]


def test_risk_tone_classifications():
    assert briefing._risk_tone(1.0, 2.0, 12)[0] == "risk-on"
    assert briefing._risk_tone(-0.9, 0.5, 22)[0] == "risk-off"
    assert briefing._risk_tone(0.1, 1.0, 14)[0] == "range-bound"
    assert briefing._risk_tone(0.6, 0.8, 15)[0] == "narrow / thin"
    assert briefing._risk_tone(-0.6, 1.5, 16)[0] == "resilient"

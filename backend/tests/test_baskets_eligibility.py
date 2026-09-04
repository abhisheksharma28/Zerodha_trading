"""Baskets Phase 5 — universe metadata + the pre-scoring eligibility screen."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.baskets import universes as U
from app.baskets.eligibility import DEFAULT_GATE, EligibilityGate, assess_member, screen_members
from app.strategies.base import Bar


def _bars(symbol: str, n: int, *, end: datetime, step_days: int = 1, close: float = 100.0,
          gap_after: int | None = None, gap_days: int = 0):
    """n daily bars ending at ``end`` (walking backwards), optional one big gap."""
    out: list[Bar] = []
    d = end
    for i in range(n):
        ts = d.isoformat()
        out.append(Bar(timestamp=ts, open=close, high=close, low=close, close=close,
                       volume=100_000, instrument=symbol))
        back = step_days
        if gap_after is not None and i == gap_after:
            back += gap_days
        d = d - timedelta(days=back)
    out.reverse()
    return out


def test_universe_metadata_covers_every_registered_universe():
    cat = U.catalog()
    assert {c["name"] for c in cat} == set(U.names())
    for c in cat:
        assert c["label"] and c["intent"] and c["curation"]
        assert c["n_members"] >= 1
    d = U.describe("LARGE_MID_ALPHA")
    assert d["n_members"] == len(d["members"]) > 20


def test_assess_member_flags_short_history_and_penny_price():
    now = datetime(2024, 6, 3)
    short = _bars("X", 40, end=now, close=3.0)
    a = assess_member("X", short, now)
    assert a.eligible is False
    assert any("bars" in r for r in a.reasons)
    assert any("floor" in r for r in a.reasons)


def test_assess_member_flags_stale_data():
    now = datetime(2024, 6, 3)
    # 300 clean bars but ending 60 days before as_of -> stale
    stale = _bars("Y", 300, end=now - timedelta(days=60))
    a = assess_member("Y", stale, now)
    assert a.eligible is False
    assert any("stale" in r for r in a.reasons)


def test_assess_member_flags_internal_gap():
    now = datetime(2024, 6, 3)
    gappy = _bars("Z", 300, end=now, gap_after=120, gap_days=45)
    a = assess_member("Z", gappy, now, gate=EligibilityGate(max_internal_gap_days=15))
    assert a.eligible is False
    assert any("gap" in r for r in a.reasons)


def test_assess_member_liquidity_gate_optional():
    now = datetime(2024, 6, 3)
    thin = _bars("L", 300, end=now)
    for b in thin:
        b.volume = 10  # ~1000 turnover
    ok_default = assess_member("L", thin, now)  # default gate: no turnover test
    assert ok_default.eligible is True
    strict = assess_member("L", thin, now, gate=EligibilityGate(min_median_turnover=1_000_000))
    assert strict.eligible is False
    assert any("turnover" in r for r in strict.reasons)


def test_screen_members_partitions_the_list():
    now = datetime(2024, 6, 3)
    bars = {
        "GOOD1": _bars("GOOD1", 300, end=now),
        "GOOD2": _bars("GOOD2", 300, end=now),
        "SHORT": _bars("SHORT", 30, end=now),
    }
    eligible, assessed = screen_members(["GOOD1", "GOOD2", "SHORT", "NOBARS"], bars, now)
    assert eligible == ["GOOD1", "GOOD2"]
    by_sym = {a.symbol: a for a in assessed}
    assert by_sym["NOBARS"].reasons == ["no price history"]
    assert DEFAULT_GATE.min_history_bars == 260


def test_universes_screen_endpoint_shape(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def fake_fetch(db, settings, *, symbols, timeframe, start, end):
        good = {s: _bars(s, 300, end=today) for s in symbols[:3]}
        return good, []

    monkeypatch.setattr("app.backtesting.adhoc.fetch_candles", fake_fetch)

    with TestClient(app) as client:
        r = client.get("/api/v1/baskets/universes")
        assert r.status_code == 200
        assert any(u["name"] == "QUALITY" for u in r.json()["universes"])

        r2 = client.get("/api/v1/baskets/universes/QUALITY/screen")
        assert r2.status_code == 200
        body = r2.json()
        assert body["universe"]["name"] == "QUALITY"
        assert body["n_eligible"] == 3
        assert set(body) >= {"gate", "eligible", "ineligible", "assessed"}

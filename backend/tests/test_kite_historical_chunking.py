"""KiteClient.get_historical_candles pages large date ranges and stitches
them (no cap on how far back a caller can ask)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.brokers.zerodha.client import KiteClient


class _StubClient(KiteClient):
    def __init__(self) -> None:  # skip the real httpx setup
        self.pages: list[tuple[datetime, datetime]] = []

    def _historical_page(self, token, interval, from_dt, to_dt, continuous, oi):  # type: ignore[override]
        self.pages.append((from_dt, to_dt))
        # one daily candle per day in [from_dt, to_dt]
        out = []
        d = from_dt
        while d <= to_dt:
            out.append([d.strftime("%Y-%m-%dT00:00:00+0530"), 1.0, 1.0, 1.0, 1.0, 100])
            d += timedelta(days=1)
        return out


def test_single_request_when_within_limit():
    c = _StubClient()
    to = datetime(2024, 6, 1)
    rows = c.get_historical_candles("T", "day", to - timedelta(days=100), to)
    assert len(c.pages) == 1
    assert len(rows) == 101


def test_large_daily_range_is_paged_and_stitched():
    c = _StubClient()
    to = datetime(2024, 1, 1)
    frm = to - timedelta(days=6000)  # ~16y, Kite's day cap is 1900
    rows = c.get_historical_candles("T", "day", frm, to)

    assert len(c.pages) >= 3
    ts = [r[0] for r in rows]
    assert ts == sorted(ts)                 # chronological
    assert len(ts) == len(set(ts))          # no boundary duplicates
    assert ts[0].startswith(frm.strftime("%Y-%m-%d"))
    assert ts[-1].startswith(to.strftime("%Y-%m-%d"))


def test_intraday_uses_a_tighter_page_size():
    c = _StubClient()
    to = datetime(2024, 1, 1)
    c.get_historical_candles("T", "5minute", to - timedelta(days=300), to)
    # 5minute cap is ~90d -> at least 4 pages for 300 days
    assert len(c.pages) >= 4

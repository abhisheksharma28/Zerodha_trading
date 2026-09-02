"""Live ticker supervisor: stays stopped without a broker, safe status shape."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.live import engine as live_engine


@pytest.mark.asyncio
async def test_start_is_noop_when_flag_unset(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "live_ticker_enabled", False, raising=False)
    await live_engine.start(s)
    status = live_engine.engine_status()
    assert status["state"] == "stopped"
    assert "ticker" not in status  # nothing constructed
    assert status["market_state"]["instrument_count"] >= 0
    assert "hub" in status


@pytest.mark.asyncio
async def test_stop_is_safe_when_never_started():
    await live_engine.stop()  # must not raise


def test_resolve_symbols_splits_known_and_unknown():
    triples, unknown = live_engine.resolve_symbols(["NSE:RELIANCE", "NSE:NOTAREALTICKER"])
    assert len(triples) == 1
    tok, inp, ts = triples[0]
    assert isinstance(tok, int) and tok > 0
    assert inp == "NSE:RELIANCE"
    assert ts == "RELIANCE"
    assert unknown == ["NSE:NOTAREALTICKER"]

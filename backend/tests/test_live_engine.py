"""Live ticker supervisor: disabled by default, safe status shape."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.live import engine as live_engine


@pytest.mark.asyncio
async def test_start_is_noop_when_disabled(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "live_ticker_enabled", False, raising=False)
    await live_engine.start(s)
    status = live_engine.engine_status()
    assert status["state"] == "disabled"
    assert "ticker" not in status  # nothing constructed
    assert status["market_state"]["instrument_count"] >= 0


@pytest.mark.asyncio
async def test_stop_is_safe_when_never_started():
    await live_engine.stop()  # must not raise

"""DB-facing helper: fetch the index history and classify the current
market regime. Cached briefly so the endpoint and the insights briefing
don't re-fetch on every call."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.regime.engine import RegimeState, classify

_INDEX = "NIFTY 50"
_VIX = "INDIA VIX"
_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}
_TTL = 120.0


def _closes(bars: list[Any]) -> list[float]:
    return [float(b.close) for b in sorted(bars, key=lambda b: str(b.timestamp)) if b.close]


def current_regime(db: Any, settings: Any, *, fresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not fresh and _CACHE["payload"] is not None and now - _CACHE["at"] < _TTL:
        return _CACHE["payload"]

    from app.backtesting.adhoc import fetch_candles

    end = datetime.now().date()
    start = end - timedelta(days=560)
    try:
        candles, _ = fetch_candles(
            db, settings, symbols=[_INDEX, _VIX], timeframe="1d",
            start=start.isoformat(), end=end.isoformat(),
        )
    except Exception as exc:  # noqa: BLE001 - never fabricate; report unavailable
        return {"available": False, "reason": str(exc)}

    idx_bars = next((v for k, v in candles.items() if k.upper() == _INDEX), [])
    vix_bars = next((v for k, v in candles.items() if k.upper() == _VIX), [])
    idx_closes = _closes(idx_bars)
    if len(idx_closes) < 30:
        return {"available": False, "reason": "insufficient index history"}

    vix_closes = _closes(vix_bars) or None
    state: RegimeState = classify(
        idx_closes, vix_closes=vix_closes, as_of_label=datetime.now(UTC).date().isoformat()
    )
    payload = {"available": True, **state.to_dict(), "index": _INDEX}
    _CACHE.update(at=now, payload=payload)
    return payload

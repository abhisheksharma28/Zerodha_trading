"""Historical-price providers for the Alpha Discovery Engine ingest job.

Twelve Data REST (free tier) for global ETFs; the Kite candle store for
Indian ETFs (added in P1b). Providers are only invoked by the one-off
``python -m app.discovery.ingest`` job — never on a request path — so the
engine itself never makes a live external call and every result stays
reproducible.
"""

from __future__ import annotations

import time
from datetime import date

import httpx

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MIN_INTERVAL_S = 8.0  # free tier: 8 requests / minute
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def twelvedata_series(
    symbol: str,
    *,
    interval: str = "1month",
    start: str = "2004-01-01",
    end: str | None = None,
    client: httpx.Client | None = None,
) -> list[tuple[date, float]]:
    """(date, close) rows, oldest first. Raises on an API error or a missing
    key so the ingest job fails loudly rather than storing a partial set."""
    s = get_settings()
    if not s.twelvedata_api_key:
        raise RuntimeError(
            "TWELVEDATA_API_KEY is not set — add it to .env "
            "(free key: https://twelvedata.com/apikey)"
        )
    end = end or date.today().isoformat()
    params = {
        "symbol": symbol, "interval": interval, "start_date": start, "end_date": end,
        "outputsize": 5000, "order": "ASC", "format": "JSON",
        "apikey": s.twelvedata_api_key,
    }
    _throttle()
    own = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        r = client.get(f"{s.twelvedata_api_base}/time_series", params=params)
        r.raise_for_status()
        body = r.json()
    finally:
        if own:
            client.close()

    if isinstance(body, dict) and body.get("status") == "error":
        raise RuntimeError(f"Twelve Data error for {symbol}: {body.get('message')}")
    values = body.get("values") if isinstance(body, dict) else None
    if not values:
        raise RuntimeError(f"Twelve Data returned no values for {symbol}")

    out: list[tuple[date, float]] = []
    for row in values:
        try:
            d = date.fromisoformat(str(row["datetime"])[:10])
            c = float(row["close"])
        except (KeyError, ValueError, TypeError):
            continue
        if c > 0:
            out.append((d, c))
    out.sort()
    logger.info("twelvedata_series", symbol=symbol, points=len(out),
                span=f"{out[0][0]}..{out[-1][0]}" if out else "none")
    return out

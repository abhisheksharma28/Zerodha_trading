"""Cache-through historical candle loader.

See docs/ZERODHA_API_NOTES.md section 2: historical data is a metered, paid
Kite resource, so backtests must never re-fetch a range that's already been
pulled. This is a simple file-based (JSON-per-key) cache under `data/` —
deliberately not a new Postgres table yet, to keep the initial schema small;
promoting this to a proper table (or a columnar store) is a natural
follow-up once real usage shows what query patterns matter.
"""

import json
from datetime import datetime
from pathlib import Path

from app.brokers.base import BrokerClient
from app.strategies.base import Bar

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "candles"


def _cache_key(instrument_token: str, interval: str, from_dt: datetime, to_dt: datetime) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{instrument_token}_{interval}_{from_dt.date()}_{to_dt.date()}.json"
    return _CACHE_DIR / fname


def get_candles(
    broker_client: BrokerClient,
    instrument_token: str,
    tradingsymbol: str,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[Bar]:
    path = _cache_key(instrument_token, interval, from_dt, to_dt)

    if path.exists():
        raw = json.loads(path.read_text())
    else:
        raw = broker_client.get_historical_candles(instrument_token, interval, from_dt, to_dt)
        path.write_text(json.dumps(raw))

    bars = []
    for row in raw:
        ts, o, hi, lo, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
        bars.append(
            Bar(timestamp=ts, open=o, high=hi, low=lo, close=c, volume=v, instrument=tradingsymbol)
        )
    return bars

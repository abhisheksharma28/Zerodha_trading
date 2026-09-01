"""Resolve a human trading symbol to a Kite ``instrument_token``.

The historical-candles endpoint is keyed by ``instrument_token``, not by
tradingsymbol, so a backtest whose universe is written as ``["RELIANCE"]``
(or ``["NSE:RELIANCE"]``) needs this lookup first. Kite publishes the full
instrument list as a plain CSV at ``/instruments/<exchange>`` that requires
no authentication, so this works even before a broker session exists. The
dump changes at most once a day, so it is cached on disk under ``data/``.
"""

import csv
import io
import time
from pathlib import Path

import httpx

from app.core.exceptions import NotFoundError

_KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments/{exchange}"
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "instruments"
_CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_path(exchange: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{exchange}.csv"


def _load_csv(exchange: str) -> str:
    path = _cache_path(exchange)
    if path.exists() and (time.time() - path.stat().st_mtime) < _CACHE_TTL_SECONDS:
        return path.read_text()

    resp = httpx.get(_KITE_INSTRUMENTS_URL.format(exchange=exchange), timeout=15.0)
    resp.raise_for_status()
    path.write_text(resp.text)
    return resp.text


def fetch_instrument_dump(exchange: str) -> str:
    """Raw Kite instrument-dump CSV for an exchange (disk-cached, ~daily).

    Public entry point used by app.services.instrument_service to build the
    canonical instrument master.
    """
    return _load_csv(exchange.strip().upper())


def resolve_instrument_token(symbol: str, *, default_exchange: str = "NSE") -> tuple[str, str]:
    """``"RELIANCE"`` or ``"NSE:RELIANCE"`` -> ``("738561", "RELIANCE")``.

    Returns ``(instrument_token, tradingsymbol)``. Raises NotFoundError if the
    symbol is not listed on the resolved exchange.
    """

    if ":" in symbol:
        exchange, tradingsymbol = symbol.split(":", 1)
    else:
        exchange, tradingsymbol = default_exchange, symbol
    exchange = exchange.strip().upper()
    tradingsymbol = tradingsymbol.strip().upper()

    reader = csv.DictReader(io.StringIO(_load_csv(exchange)))
    for row in reader:
        if row["tradingsymbol"].upper() == tradingsymbol:
            return row["instrument_token"], tradingsymbol

    raise NotFoundError(f"Instrument '{tradingsymbol}' not found on {exchange}.")

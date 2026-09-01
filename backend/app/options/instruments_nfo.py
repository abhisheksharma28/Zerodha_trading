"""NFO (F&O) instrument master for a given underlying.

Kite publishes the full derivatives list as a plain CSV at
``/instruments/NFO`` with no authentication, so this works before a broker
session exists. The dump changes at most once a trading day, so it is
cached on disk under ``data/`` for a day. Everything the options strategy
needs — listed expiries, the strike grid, lot size, and the exact
tradingsymbol / instrument_token for a (expiry, strike, CE|PE) triple —
comes from here.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from app.core.exceptions import NotFoundError

_URL = "https://api.kite.trade/instruments/NFO"
_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "instruments" / "NFO.csv"
_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class OptionContract:
    instrument_token: str
    tradingsymbol: str
    name: str          # underlying, e.g. "NIFTY"
    expiry: date
    strike: float
    option_type: str   # "CE" | "PE"
    lot_size: int
    tick_size: float
    exchange: str = "NFO"


def _load_csv(*, force_refresh: bool = False) -> str:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not force_refresh and _CACHE.exists() and (time.time() - _CACHE.stat().st_mtime) < _TTL_SECONDS:
        return _CACHE.read_text()
    resp = httpx.get(_URL, timeout=30.0)
    resp.raise_for_status()
    _CACHE.write_text(resp.text)
    return resp.text


def load_option_contracts(underlying: str, *, force_refresh: bool = False) -> list[OptionContract]:
    """All listed CE/PE contracts for ``underlying`` (e.g. ``"NIFTY"``)."""
    underlying = underlying.strip().upper()
    reader = csv.DictReader(io.StringIO(_load_csv(force_refresh=force_refresh)))
    out: list[OptionContract] = []
    for row in reader:
        if row["name"].strip().upper() != underlying:
            continue
        if row["instrument_type"] not in ("CE", "PE"):
            continue
        try:
            exp = date.fromisoformat(row["expiry"])
        except ValueError:
            continue
        out.append(
            OptionContract(
                instrument_token=row["instrument_token"],
                tradingsymbol=row["tradingsymbol"],
                name=underlying,
                expiry=exp,
                strike=float(row["strike"]),
                option_type=row["instrument_type"],
                lot_size=int(float(row["lot_size"])),
                tick_size=float(row["tick_size"] or 0.05),
            )
        )
    if not out:
        raise NotFoundError(f"No NFO option contracts found for underlying '{underlying}'.")
    return out


def lot_size_for(underlying: str, expiry: date | None = None) -> int:
    """Current exchange lot size for the underlying's options. ``expiry`` is
    accepted for a future historical-override hook; today all listed
    contracts for an underlying share one lot size."""
    contracts = load_option_contracts(underlying)
    if expiry is not None:
        for c in contracts:
            if c.expiry == expiry:
                return c.lot_size
    return contracts[0].lot_size

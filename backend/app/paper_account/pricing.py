"""Live prices for the paper account: the in-process Kite tick state first,
then a batched REST quote for anything the feed is missing. Also resolves
an instrument (segment, asset class, lot size, tick size) for the order pad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_scanner import marketdata as md
from app.services import broker_service, instrument_service

logger = get_logger(__name__)
_STALE_S = 20.0


@dataclass
class Quote:
    ref: str
    ltp: float | None
    prev_close: float | None


def _from_ticks(token: str | None) -> float | None:
    if not token or not str(token).isdigit():
        return None
    try:
        from app.live.market_state import MARKET_STATE

        age = MARKET_STATE.age_seconds(int(token))
        if age is not None and age <= _STALE_S:
            return MARKET_STATE.last_price(int(token))
    except Exception:  # noqa: BLE001
        return None
    return None


def quotes(db: Session, settings: Settings, refs: list[dict[str, Any]]) -> dict[str, Quote]:
    """``refs`` items: {"ref": "NSE:INFY", "token": "408065"}. Returns
    {ref -> Quote}. Missing prices come back as None (never invented)."""
    out: dict[str, Quote] = {}
    misses: list[str] = []
    for r in refs:
        p = _from_ticks(r.get("token"))
        out[r["ref"]] = Quote(r["ref"], p, None)
        if p is None:
            misses.append(r["ref"])
    if misses:
        try:
            client = broker_service.build_authenticated_client(db, settings)
        except Exception:  # noqa: BLE001
            client = None
        if client is not None:
            data = md.batched_quotes(client, misses)
            for ref in misses:
                row = data.get(ref) or {}
                ltp = row.get("last_price")
                pc = (row.get("ohlc") or {}).get("close")
                out[ref] = Quote(
                    ref,
                    float(ltp) if ltp is not None else None,
                    float(pc) if pc is not None else None,
                )
    return out


def one_quote(db: Session, settings: Settings, ref: str, token: str | None) -> Quote:
    return quotes(db, settings, [{"ref": ref, "token": token}]).get(ref, Quote(ref, None, None))


@dataclass
class InstrumentInfo:
    exchange: str
    tradingsymbol: str
    instrument_token: str | None
    segment: str | None
    asset_class: str  # EQUITY | FUT | OPT
    lot_size: int
    tick_size: float
    name: str | None


def resolve(db: Session, exchange: str, tradingsymbol: str) -> InstrumentInfo | None:
    inst = instrument_service.get(db, exchange, tradingsymbol)
    if inst is None:
        hits = instrument_service.search(db, tradingsymbol, exchange=exchange, limit=1)
        inst = hits[0] if hits else None
    if inst is None:
        return None
    itype = (inst.instrument_type or "EQ").upper()
    asset = "FUT" if itype == "FUT" else "OPT" if itype in ("CE", "PE") else "EQUITY"
    return InstrumentInfo(
        exchange=inst.exchange,
        tradingsymbol=inst.tradingsymbol,
        instrument_token=inst.instrument_token,
        segment=inst.segment,
        asset_class=asset,
        lot_size=int(inst.lot_size or 1) or 1,
        tick_size=float(inst.tick_size or 0.05) or 0.05,
        name=inst.name,
    )

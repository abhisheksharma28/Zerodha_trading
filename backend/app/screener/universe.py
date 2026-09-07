"""The universe the screener scores: the *liquid* slice of NSE where the
free fundamentals feed is actually reliable.

= every F&O underlying  ∪  NIFTY 200  ∪  the most-traded remaining NSE
equities (by a cheap price×volume proxy from one batched quote call),
truncated to ``screener_universe_max``. Non-equity lines (bonds, SGBs,
gilts, rights) are screened out with the same regex the market scanner
uses.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.market_data.nse_universe import NIFTY_200
from app.market_scanner.universe import _looks_like_equity  # noqa: PLC2701 - shared screen
from app.models.instrument import Instrument

logger = get_logger(__name__)

_QUOTE_BATCH = 200


def _fno_underlyings(db: Session) -> set[str]:
    rows = db.execute(
        select(Instrument.name)
        .distinct()
        .where(
            Instrument.exchange == "NFO",
            Instrument.instrument_type == "FUT",
            Instrument.active.is_(True),
            Instrument.name.is_not(None),
        )
    ).scalars().all()
    eq = _nse_equities(db)
    return {n for n in rows if n in eq}


def _nse_equities(db: Session) -> set[str]:
    rows = db.execute(
        select(Instrument.tradingsymbol).where(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.active.is_(True),
        )
    ).scalars().all()
    return {r for r in rows if _looks_like_equity(r)}


def build(db: Session, client: Any, *, cap: int) -> list[str]:
    """Return up to ``cap`` NSE tradingsymbols, most-liquid first."""
    equities = _nse_equities(db)
    core = {s for s in NIFTY_200 if s in equities} | _fno_underlyings(db)

    ranked = sorted(core)
    if len(ranked) < cap:
        # top up with the most-traded of the remaining equities
        rest = sorted(equities - core)
        traded = _traded_value(client, rest)
        rest.sort(key=lambda s: traded.get(s, 0.0), reverse=True)
        ranked = ranked + [s for s in rest if traded.get(s, 0.0) > 0][: cap - len(ranked)]

    out = ranked[:cap]
    logger.info("screener_universe_built", core=len(core), total=len(out))
    return out


def _traded_value(client: Any, symbols: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i in range(0, len(symbols), _QUOTE_BATCH):
        batch = [f"NSE:{s}" for s in symbols[i : i + _QUOTE_BATCH]]
        try:
            q = client.get_quote(batch)
        except Exception as exc:  # noqa: BLE001 - a bad batch just means fewer top-ups
            logger.warning("screener_universe_quote_failed", size=len(batch), error=str(exc))
            continue
        for key, row in q.items():
            sym = key.split(":", 1)[-1]
            ltp = row.get("last_price") or 0.0
            vol = row.get("volume") or 0.0
            out[sym] = float(ltp) * float(vol)
    return out

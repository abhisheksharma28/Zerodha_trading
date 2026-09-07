"""The universe the screener scores. Selectable scope (a dropdown in the
UI); non-equity lines (bonds, SGBs, gilts, rights) are always screened
out with the same regex the market scanner uses.

* ``fno``      — only NSE stocks with listed single-stock futures (~210)
* ``nifty200`` — those ∪ the NIFTY 200 (~260)
* ``broad500`` — those ∪ the next most-traded NSE equities, to ~500
* ``all``      — every active NSE equity (~2000). Small caps frequently
                 have no fundamentals from the free feed and land in the
                 low-confidence HOLD bucket; their technical rating still
                 computes from candles.
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

SCOPES: list[dict[str, str]] = [
    {"key": "fno", "label": "F&O stocks (~210)",
     "note": "Only NSE stocks with listed futures — cleanest data, ~2 min."},
    {"key": "nifty200", "label": "Nifty 200 + F&O (~260)",
     "note": "Large & mid cap. Reliable fundamentals."},
    {"key": "broad500", "label": "Broad ~500",
     "note": "F&O ∪ Nifty 200 ∪ the next most-traded names."},
    {"key": "all", "label": "All NSE stocks (~2000)",
     "note": "Whole market. Small caps often have no fundamentals from the "
             "free feed — those show as low-confidence HOLD; the technical "
             "rating still computes. Sweep takes ~15-20 min."},
]
_SCOPE_KEYS = {s["key"] for s in SCOPES}
DEFAULT_SCOPE = "broad500"


def normalise_scope(scope: str | None) -> str:
    s = (scope or "").strip().lower()
    return s if s in _SCOPE_KEYS else DEFAULT_SCOPE


def _fno_underlyings(db: Session, equities: set[str]) -> set[str]:
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
    return {n for n in rows if n in equities}


def _nse_equities(db: Session) -> set[str]:
    rows = db.execute(
        select(Instrument.tradingsymbol).where(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.active.is_(True),
        )
    ).scalars().all()
    return {r for r in rows if _looks_like_equity(r)}


def build(db: Session, client: Any, *, scope: str, cap: int) -> list[str]:
    """NSE tradingsymbols for the given scope, most-liquid first, ``cap``-limited."""
    scope = normalise_scope(scope)
    equities = _nse_equities(db)
    fno = _fno_underlyings(db, equities)

    if scope == "fno":
        out = sorted(fno)
    elif scope == "nifty200":
        out = sorted({s for s in NIFTY_200 if s in equities} | fno)
    elif scope == "all":
        out = sorted(equities)
    else:  # broad500
        core = {s for s in NIFTY_200 if s in equities} | fno
        ranked = sorted(core)
        target = min(cap, 500)
        if len(ranked) < target:
            rest = sorted(equities - core)
            traded = _traded_value(client, rest)
            rest.sort(key=lambda s: traded.get(s, 0.0), reverse=True)
            ranked += [s for s in rest if traded.get(s, 0.0) > 0][: target - len(ranked)]
        out = ranked[:target]

    out = out[:cap]
    logger.info("screener_universe_built", scope=scope, total=len(out))
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

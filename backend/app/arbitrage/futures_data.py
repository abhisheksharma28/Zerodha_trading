"""F&O contract resolution for the basis / carry / calendar strategies.

Kite's historical API serves *listed* contracts reliably and expired ones
patchily, and the local instrument master only holds currently-listed
rows. So this helper resolves the near / far FUT tradingsymbols for an
underlying and their expiry epochs from the instrument table; a multi-
expiry historical backtest that needs data for contracts that have since
expired will simply come up short, which the service surfaces rather than
faking a continuous series.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument


def near_far_futures(db: Session, underlying: str) -> list[dict[str, object]]:
    """Currently-listed FUT contracts for ``underlying``, soonest expiry first."""
    rows = db.execute(
        select(Instrument)
        .where(Instrument.instrument_type == "FUT")
        .where(func.lower(func.coalesce(Instrument.underlying, "")) == underlying.strip().lower())
        .where(Instrument.active.is_(True))
        .where(Instrument.expiry.is_not(None))
        .order_by(Instrument.expiry.asc())
    ).scalars().all()
    out: list[dict[str, object]] = []
    for r in rows:
        exp = r.expiry
        out.append({
            "tradingsymbol": f"{r.exchange}:{r.tradingsymbol}",
            "expiry": exp.isoformat() if exp else None,
            "expiry_epoch": (
                datetime(exp.year, exp.month, exp.day, 15, 30, tzinfo=UTC).timestamp()
                if exp else 0.0
            ),
        })
    return out


def expiry_epoch_for(db: Session, symbol: str) -> float:
    """Best-effort expiry epoch for a resolved FUT tradingsymbol (``EXCH:SYM``)."""
    sym = symbol.split(":")[-1].strip().upper()
    row = db.execute(
        select(Instrument.expiry)
        .where(func.upper(Instrument.tradingsymbol) == sym)
        .where(Instrument.instrument_type == "FUT")
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return 0.0
    return datetime(row.year, row.month, row.day, 15, 30, tzinfo=UTC).timestamp()

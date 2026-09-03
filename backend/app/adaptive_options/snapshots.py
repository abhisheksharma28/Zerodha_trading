"""Read/write the rolling option-chain snapshot history.

The engines (PCR percentile / transition, IV rank, OI-wall migration) all
work against this. ``record`` is throttled so a fast dashboard poll does
not flood the table.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adaptive_options.types import ChainSnapshot
from app.models.adaptive_options import AdaptiveChainSnapshot

_MIN_GAP_SECONDS = 90.0


def _expiry_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def latest(db: Session, underlying: str, expiry: str) -> AdaptiveChainSnapshot | None:
    return db.execute(
        select(AdaptiveChainSnapshot)
        .where(
            AdaptiveChainSnapshot.underlying == underlying.upper(),
            AdaptiveChainSnapshot.expiry == _expiry_date(expiry),
        )
        .order_by(AdaptiveChainSnapshot.captured_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def prev_oi_rows(db: Session, underlying: str, expiry: str) -> dict[float, dict[str, float]]:
    """Per-strike {call_oi, put_oi} from the most recent stored snapshot, so
    the new snapshot can compute change-in-OI."""
    row = latest(db, underlying, expiry)
    if row is None:
        return {}
    out: dict[float, dict[str, float]] = {}
    for r in (row.payload or {}).get("rows", []):
        try:
            out[float(r["strike"])] = {
                "call_oi": float(r.get("call_oi") or 0.0),
                "put_oi": float(r.get("put_oi") or 0.0),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_history(
    db: Session, underlying: str, expiry: str, *, limit: int = 90
) -> list[dict[str, Any]]:
    """Oldest-first series the engines consume."""
    rows = db.execute(
        select(AdaptiveChainSnapshot)
        .where(
            AdaptiveChainSnapshot.underlying == underlying.upper(),
            AdaptiveChainSnapshot.expiry == _expiry_date(expiry),
        )
        .order_by(AdaptiveChainSnapshot.captured_at.desc())
        .limit(limit)
    ).scalars().all()
    out = [
        {
            "captured_at": r.captured_at.isoformat(),
            "spot": float(r.spot) if r.spot is not None else None,
            "oi_pcr": float(r.oi_pcr) if r.oi_pcr is not None else None,
            "weighted_pcr": float(r.weighted_pcr) if r.weighted_pcr is not None else None,
            "atm_iv": float(r.atm_iv) if r.atm_iv is not None else None,
            "put_support": float(r.put_support) if r.put_support is not None else None,
            "call_resistance": float(r.call_resistance) if r.call_resistance is not None else None,
        }
        for r in rows
    ]
    out.reverse()
    return out


def record(
    db: Session,
    snap: ChainSnapshot,
    *,
    oi_pcr: float | None = None,
    weighted_pcr: float | None = None,
    atm_iv: float | None = None,
    put_support: float | None = None,
    call_resistance: float | None = None,
    source: str = "live",
    force: bool = False,
) -> AdaptiveChainSnapshot | None:
    """Insert a snapshot unless (a) the chain timestamp has not advanced since
    the last stored one (e.g. market closed — nothing new to record), or
    (b) a row was *written* < ``_MIN_GAP_SECONDS`` ago."""
    prev = latest(db, snap.underlying, snap.expiry)
    if prev is not None and not force:
        prev_cap = prev.captured_at if prev.captured_at.tzinfo else prev.captured_at.replace(tzinfo=UTC)
        snap_cap = snap.as_of if snap.as_of.tzinfo else snap.as_of.replace(tzinfo=UTC)
        if snap_cap <= prev_cap:
            return None
        wrote_at = prev.created_at if prev.created_at and prev.created_at.tzinfo \
            else (prev.created_at.replace(tzinfo=UTC) if prev.created_at else None)
        if wrote_at and datetime.now(UTC) - wrote_at < timedelta(seconds=_MIN_GAP_SECONDS):
            return None

    # compact payload: strip Nones, keep the per-strike OI/vol for replay + ΔOI
    compact_rows = [
        {"strike": r.strike, "call_oi": r.call_oi, "put_oi": r.put_oi,
         "call_volume": r.call_volume, "put_volume": r.put_volume,
         "call_iv": r.call_iv, "put_iv": r.put_iv}
        for r in snap.rows
    ]
    obj = AdaptiveChainSnapshot(
        underlying=snap.underlying.upper(),
        expiry=_expiry_date(snap.expiry),
        captured_at=snap.as_of if snap.as_of.tzinfo else snap.as_of.replace(tzinfo=UTC),
        source=source,
        spot=snap.spot,
        dte=snap.dte,
        oi_pcr=oi_pcr,
        weighted_pcr=weighted_pcr,
        atm_iv=atm_iv,
        put_support=put_support,
        call_resistance=call_resistance,
        payload={"spot": snap.spot, "dte": snap.dte, "rows": compact_rows},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

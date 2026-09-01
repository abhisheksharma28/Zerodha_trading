"""Canonical NSE (and friends) instrument master: sync + search.

``sync`` pulls Zerodha's unauthenticated instrument-dump CSVs (via
app.market_data.instruments.fetch_instrument_dump), upserts every row into
the ``instruments`` table keyed by ``(exchange, tradingsymbol)``, and flips
anything absent from the fresh dump to ``active = False``. ``search`` is the
ranked lookup that powers every instrument selector in the UI, so nobody has
to type raw symbols.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.market_data.instruments import fetch_instrument_dump
from app.models.instrument import Instrument

logger = get_logger(__name__)

DEFAULT_EXCHANGES: tuple[str, ...] = ("NSE", "NFO", "BSE")
_DERIVATIVE_TYPES = {"FUT", "CE", "PE"}
_UPSERT_BATCH = 2000
# Instrument-type sort priority for search results: cash first, then futures,
# then options — a user searching "NIFTY" wants the index before 3000 strikes.
_TYPE_ORDER = {"EQ": 0, "FUT": 1, "CE": 2, "PE": 2}


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _num(value: str) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f or None


def _row_to_values(row: dict[str, str], *, now: datetime) -> dict[str, Any] | None:
    ts = (row.get("tradingsymbol") or "").strip().upper()
    exch = (row.get("exchange") or "").strip().upper()
    if not ts or not exch:
        return None
    itype = (row.get("instrument_type") or "").strip().upper()
    name = (row.get("name") or "").strip() or None
    return {
        "instrument_token": (row.get("instrument_token") or "").strip(),
        "exchange_token": (row.get("exchange_token") or "").strip() or None,
        "tradingsymbol": ts,
        "name": name,
        "exchange": exch,
        "segment": (row.get("segment") or "").strip().upper() or exch,
        "instrument_type": itype or "EQ",
        "expiry": _parse_date(row.get("expiry", "")),
        "strike": _num(row.get("strike", "")),
        "tick_size": _num(row.get("tick_size", "")),
        "lot_size": int(_num(row.get("lot_size", "")) or 0) or None,
        "underlying": name if itype in _DERIVATIVE_TYPES else None,
        "active": True,
        "last_synced_at": now,
    }


def _iter_dump_rows(exchange: str) -> list[dict[str, str]]:
    text = fetch_instrument_dump(exchange)
    return list(csv.DictReader(io.StringIO(text)))


def sync(
    db: Session,
    exchanges: tuple[str, ...] | list[str] = DEFAULT_EXCHANGES,
    *,
    deactivate_missing: bool = True,
) -> dict[str, Any]:
    """Refresh the instrument master from Zerodha's dumps. Idempotent."""
    now = datetime.now(UTC)
    per_exchange: dict[str, dict[str, int]] = {}

    for exchange in (e.strip().upper() for e in exchanges):
        rows = _iter_dump_rows(exchange)
        values: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in rows:
            v = _row_to_values(raw, now=now)
            if v is None or v["tradingsymbol"] in seen:
                continue
            seen.add(v["tradingsymbol"])
            values.append(v)

        for start in range(0, len(values), _UPSERT_BATCH):
            batch = values[start : start + _UPSERT_BATCH]
            stmt = pg_insert(Instrument).values(batch)
            update_cols = {
                c: stmt.excluded[c]
                for c in (
                    "instrument_token", "exchange_token", "name", "segment",
                    "instrument_type", "expiry", "strike", "tick_size", "lot_size",
                    "underlying", "active", "last_synced_at",
                )
            }
            stmt = stmt.on_conflict_do_update(
                constraint="uq_instruments_exchange_symbol", set_=update_cols
            )
            db.execute(stmt)

        deactivated = 0
        if deactivate_missing:
            result = db.execute(
                update(Instrument)
                .where(Instrument.exchange == exchange)
                .where(Instrument.last_synced_at < now)
                .where(Instrument.active.is_(True))
                .values(active=False)
            )
            deactivated = int(getattr(result, "rowcount", 0) or 0)

        per_exchange[exchange] = {"rows": len(values), "deactivated": deactivated}
        logger.info("instrument_sync_exchange", exchange=exchange, **per_exchange[exchange])

    db.commit()
    total = sum(v["rows"] for v in per_exchange.values())
    return {"synced_at": now.isoformat(), "total": total, "by_exchange": per_exchange}


# --- reads --------------------------------------------------------------

def _q(s: str) -> str:
    return s.strip().lower()


def search(
    db: Session,
    query: str,
    *,
    exchange: str | None = None,
    segment: str | None = None,
    instrument_type: str | None = None,
    active_only: bool = True,
    limit: int = 25,
) -> list[Instrument]:
    """Ranked lookup: exact symbol > symbol prefix > name prefix > contains."""
    q = _q(query)
    if not q:
        return []

    sym = func.lower(Instrument.tradingsymbol)
    nm = func.lower(func.coalesce(Instrument.name, ""))
    und = func.lower(func.coalesce(Instrument.underlying, ""))

    rank = case(
        (sym == q, 0),
        (sym.like(f"{q}%"), 1),
        (nm.like(f"{q}%"), 2),
        (und == q, 2),
        else_=3,
    ).label("rank")

    type_rank = case(_TYPE_ORDER, value=Instrument.instrument_type, else_=9)

    stmt = select(Instrument, rank).where(
        sym.like(f"%{q}%") | nm.like(f"%{q}%") | (und == q)
    )
    if active_only:
        stmt = stmt.where(Instrument.active.is_(True))
    if exchange:
        stmt = stmt.where(Instrument.exchange == exchange.strip().upper())
    if segment:
        stmt = stmt.where(Instrument.segment == segment.strip().upper())
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type.strip().upper())

    stmt = stmt.order_by(
        rank,
        type_rank,
        Instrument.expiry.asc().nulls_first(),
        func.length(Instrument.tradingsymbol),
        Instrument.tradingsymbol,
    ).limit(min(max(limit, 1), 100))

    return [row[0] for row in db.execute(stmt).all()]


def get_by_token(db: Session, instrument_token: str) -> Instrument | None:
    return db.execute(
        select(Instrument).where(Instrument.instrument_token == str(instrument_token)).limit(1)
    ).scalar_one_or_none()


def get(db: Session, exchange: str, tradingsymbol: str) -> Instrument | None:
    return db.execute(
        select(Instrument)
        .where(Instrument.exchange == exchange.strip().upper())
        .where(Instrument.tradingsymbol == tradingsymbol.strip().upper())
        .limit(1)
    ).scalar_one_or_none()


def resolve_many(db: Session, raw: list[str], *, default_exchange: str = "NSE") -> dict[str, Any]:
    """Resolve a free-text list ('NSE:INFY, itc, reliance', pasted lines, …)
    against the instrument master. Returns canonical EXCHANGE:SYMBOL refs for
    what matched and the raw tokens that didn't."""
    tokens: list[str] = []
    for chunk in raw:
        for part in chunk.replace("\n", ",").replace(";", ",").split(","):
            p = part.strip()
            if p:
                tokens.append(p)

    resolved: list[dict[str, Any]] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if ":" in tok:
            ex, sym = tok.split(":", 1)
        else:
            ex, sym = default_exchange, tok
        ex, sym = ex.strip().upper(), sym.strip().upper()
        inst = get(db, ex, sym)
        if inst is None:
            # fall back to a ranked search (company name, partial symbol)
            hits = search(db, sym, exchange=ex, instrument_type="EQ", limit=1)
            inst = hits[0] if hits else None
        if inst is None:
            unresolved.append(tok)
            continue
        ref = f"{inst.exchange}:{inst.tradingsymbol}"
        if ref in seen:
            continue
        seen.add(ref)
        resolved.append({
            "ref": ref,
            "tradingsymbol": inst.tradingsymbol,
            "name": inst.name,
            "exchange": inst.exchange,
            "instrument_type": inst.instrument_type,
        })
    return {"resolved": resolved, "unresolved": unresolved}


def underlyings(db: Session, exchange: str = "NFO") -> list[str]:
    rows = db.execute(
        select(Instrument.underlying)
        .where(Instrument.exchange == exchange.strip().upper())
        .where(Instrument.underlying.is_not(None))
        .where(Instrument.active.is_(True))
        .distinct()
        .order_by(Instrument.underlying)
    ).scalars().all()
    return [r for r in rows if r]


def expiries(db: Session, underlying: str, *, exchange: str = "NFO") -> list[str]:
    rows = db.execute(
        select(Instrument.expiry)
        .where(Instrument.exchange == exchange.strip().upper())
        .where(func.lower(Instrument.underlying) == _q(underlying))
        .where(Instrument.expiry.is_not(None))
        .where(Instrument.active.is_(True))
        .distinct()
        .order_by(Instrument.expiry)
    ).scalars().all()
    return [d.isoformat() for d in rows if d]


def option_strikes(
    db: Session, underlying: str, expiry: str, *, exchange: str = "NFO"
) -> list[dict[str, Any]]:
    exp = _parse_date(expiry)
    rows = db.execute(
        select(Instrument)
        .where(Instrument.exchange == exchange.strip().upper())
        .where(func.lower(Instrument.underlying) == _q(underlying))
        .where(Instrument.expiry == exp)
        .where(Instrument.instrument_type.in_(("CE", "PE")))
        .where(Instrument.active.is_(True))
        .order_by(Instrument.strike, Instrument.instrument_type)
    ).scalars().all()
    return [
        {
            "strike": float(r.strike) if r.strike is not None else None,
            "option_type": r.instrument_type,
            "tradingsymbol": r.tradingsymbol,
            "instrument_token": r.instrument_token,
            "lot_size": r.lot_size,
        }
        for r in rows
    ]

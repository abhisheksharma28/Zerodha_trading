"""Canonical instrument master: search + selection endpoints.

Every instrument selector in the UI reads from here so a user never has to
type a raw tradingsymbol. ``POST /sync`` refreshes the master from Zerodha's
public instrument dumps (safe to call repeatedly; a scheduled worker is the
natural follow-up).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.exceptions import NotFoundError
from app.schemas.instrument import InstrumentRead, OptionStrikeRow, SyncResult
from app.services import instrument_service

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("/search", response_model=list[InstrumentRead])
def search(
    q: str = Query(..., min_length=1, description="Symbol, company name or underlying"),
    exchange: str | None = None,
    segment: str | None = None,
    instrument_type: str | None = Query(None, description="EQ | FUT | CE | PE"),
    active_only: bool = True,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return instrument_service.search(
        db, q, exchange=exchange, segment=segment, instrument_type=instrument_type,
        active_only=active_only, limit=limit,
    )


@router.get("/underlyings", response_model=list[str])
def underlyings(exchange: str = "NFO", db: Session = Depends(get_db)):
    return instrument_service.underlyings(db, exchange=exchange)


@router.get("/{underlying}/expiries", response_model=list[str])
def expiries(underlying: str, exchange: str = "NFO", db: Session = Depends(get_db)):
    return instrument_service.expiries(db, underlying, exchange=exchange)


@router.get("/{underlying}/strikes", response_model=list[OptionStrikeRow])
def strikes(
    underlying: str,
    expiry: str = Query(..., description="YYYY-MM-DD"),
    exchange: str = "NFO",
    db: Session = Depends(get_db),
):
    return instrument_service.option_strikes(db, underlying, expiry, exchange=exchange)


@router.get("/token/{instrument_token}", response_model=InstrumentRead)
def get_by_token(instrument_token: str, db: Session = Depends(get_db)):
    row = instrument_service.get_by_token(db, instrument_token)
    if row is None:
        raise NotFoundError(f"No instrument with token {instrument_token}")
    return row


@router.get("/{exchange}/{tradingsymbol}", response_model=InstrumentRead)
def get_one(exchange: str, tradingsymbol: str, db: Session = Depends(get_db)):
    row = instrument_service.get(db, exchange, tradingsymbol)
    if row is None:
        raise NotFoundError(f"{exchange}:{tradingsymbol} not found in the instrument master")
    return row


@router.post("/sync", response_model=SyncResult)
def sync(
    exchanges: list[str] | None = Query(None, description="Defaults to NSE, NFO, BSE"),
    db: Session = Depends(get_db),
):
    ex = tuple(exchanges) if exchanges else instrument_service.DEFAULT_EXCHANGES
    return instrument_service.sync(db, ex)

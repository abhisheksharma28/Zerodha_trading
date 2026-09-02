"""Order-flow analytics API (modular extension - see app/orderflow).

Every response carries a data-quality ``tier`` + ``caveats`` so the UI can
show the TRUE/ESTIMATED/LIMITED/UNSUPPORTED badge and never presents an
approximation as exchange-confirmed order flow.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.backtesting.timeframes import UnknownTimeframeError, kite_interval, resolve
from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import BrokerNotConnectedError, ValidationError
from app.market_data.instruments import resolve_instrument_token
from app.orderflow import (
    ORDERFLOW_DELTA,
    Candle,
    assess_historical,
    assess_live,
    build_volume_profile,
    session_anchor_ts,
    vwap_series,
)
from app.orderflow.types import DataTier
from app.services import broker_service, instrument_service
from app.services.market_data_service import _epoch, _parse_day

router = APIRouter(prefix="/orderflow", tags=["orderflow"])

_DEFAULT_DAYS = {"1m": 2, "3m": 5, "5m": 10, "15m": 20, "30m": 40, "1h": 60, "1d": 250}


def _fetch_candles(
    db: Session, settings: Settings, *, symbol: str, timeframe: str,
    days: int | None, from_date: str | None, to_date: str | None,
) -> tuple[list[Candle], str, float | None, str | None]:
    """Return (candles, tradingsymbol, tick_size, error). ``error`` set ->
    candles empty."""
    try:
        tf = resolve(timeframe)
    except UnknownTimeframeError as exc:
        raise ValidationError(str(exc)) from exc
    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        return [], symbol, None, str(exc)
    try:
        token, tradingsymbol = resolve_instrument_token(symbol)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Unknown instrument '{symbol}'.") from exc

    fd, td = _parse_day(from_date), _parse_day(to_date)
    if fd:
        from_dt, to_dt = fd, (td or datetime.now())
    else:
        span = days or _DEFAULT_DAYS.get(tf.token, 10)
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=span)

    try:
        rows = client.get_historical_candles(token, kite_interval(tf.token), from_dt, to_dt)
    except Exception as exc:  # noqa: BLE001
        return [], tradingsymbol, None, f"Historical data unavailable: {exc}"

    inst = instrument_service.get_by_token(db, str(token))
    tick_size = float(inst.tick_size) if inst and inst.tick_size else None
    candles = [
        Candle(ts=_epoch(r[0]), open=r[1], high=r[2], low=r[3], close=r[4],
               volume=(r[5] if len(r) > 5 else 0) or 0)
        for r in rows
    ]
    return candles, tradingsymbol, tick_size, None


@router.get("/capabilities")
def capabilities(scope: str = Query("all", pattern="^(all|live|historical)$")) -> dict[str, Any]:
    live = assess_live().as_dict()
    hist = assess_historical().as_dict()
    if scope == "live":
        return live
    if scope == "historical":
        return hist
    return {"live": live, "historical": hist}


@router.get("/volume-profile")
def volume_profile(
    symbol: str = Query(..., description="e.g. NSE:RELIANCE or RELIANCE"),
    timeframe: str = Query("1m"),
    days: int | None = Query(None, ge=1),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    value_area: float = Query(0.70, ge=0.5, le=0.95),
    bin_multiple: int = Query(1, ge=1, le=50),
    price_min: float | None = Query(None),
    price_max: float | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    candles, tradingsymbol, tick_size, err = _fetch_candles(
        db, settings, symbol=symbol, timeframe=timeframe, days=days,
        from_date=from_date, to_date=to_date,
    )
    cap = assess_historical().as_dict()
    if err:
        return {"available": False, "reason": err, "symbol": tradingsymbol,
                "timeframe": timeframe, "capabilities": cap}
    profile = build_volume_profile(
        candles, tick_size=tick_size, bin_multiple=bin_multiple, value_area=value_area,
        price_min=price_min, price_max=price_max, source_interval=timeframe,
        tier=DataTier.LIMITED,
    )
    return {
        "available": True,
        "symbol": tradingsymbol,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "profile": profile.as_dict(),
        "capabilities": cap,
    }


@router.get("/vwap")
def vwap(
    symbol: str = Query(...),
    timeframe: str = Query("5m"),
    days: int | None = Query(None, ge=1),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    anchor: str | None = Query(None, description="ISO datetime; default = last session open"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    candles, tradingsymbol, _tick, err = _fetch_candles(
        db, settings, symbol=symbol, timeframe=timeframe, days=days,
        from_date=from_date, to_date=to_date,
    )
    cap = assess_historical().as_dict()
    if err:
        return {"available": False, "reason": err, "symbol": tradingsymbol,
                "timeframe": timeframe, "capabilities": cap}

    anchor_ts: int | None = None
    if anchor:
        parsed = _parse_day(anchor)
        if parsed is not None:
            anchor_ts = int(parsed.timestamp()) + (5 * 3600 + 30 * 60)
    if anchor_ts is None:
        anchor_ts = session_anchor_ts(candles)

    series = vwap_series(candles, anchor_ts=anchor_ts)
    return {
        "available": True,
        "symbol": tradingsymbol,
        "timeframe": timeframe,
        "vwap": series.as_dict(),
        "capabilities": cap,
    }


@router.get("/estimated-delta")
def estimated_delta(
    symbol: str = Query(...),
    limit: int = Query(240, ge=1, le=720),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        token, tradingsymbol = resolve_instrument_token(symbol)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Unknown instrument '{symbol}'.") from exc
    data = ORDERFLOW_DELTA.snapshot(int(token), limit=limit)
    data["symbol"] = tradingsymbol
    data["capabilities"] = assess_live().as_dict()
    return data

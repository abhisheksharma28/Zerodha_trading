"""Stock-futures expression for a bearish (or bullish) swing view.

NSE cash has no naked delivery short — you can only sell shares you hold,
and a short CNC position is auto-squared / goes to exchange auction. So a
multi-day bearish idea on an F&O stock is expressed by shorting the
near-month **single-stock future** (NFO, NRML, roll before expiry).

Entry / stop / target stay on the underlying spot — the future tracks it
with a small basis and is managed against the same levels.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument

# rough SPAN + exposure margin as a fraction of contract value (varies by
# stock and volatility; a placeholder so the card can show a ballpark)
_MARGIN_PCT = 0.20


def near_month_future(db: Session, root: str) -> Instrument | None:
    """The nearest non-expired monthly NFO future for an F&O underlying."""
    if not root:
        return None
    r = root.strip().upper()
    return db.execute(
        select(Instrument)
        .where(
            Instrument.exchange == "NFO",
            Instrument.instrument_type == "FUT",
            Instrument.active.is_(True),
            Instrument.expiry.is_not(None),
            Instrument.expiry >= date.today(),
            or_(Instrument.underlying == r, Instrument.name == r),
        )
        .order_by(Instrument.expiry)
        .limit(1)
    ).scalars().first()


def futures_block(
    fut: Instrument, spot: float, direction: str, *, ltp: float | None = None
) -> dict[str, Any]:
    lot = int(fut.lot_size or 1)
    px = float(ltp or spot or 0.0)
    cval = px * lot
    dte = (fut.expiry - date.today()).days if fut.expiry else None
    side = "SELL" if direction == "SHORT" else "BUY"
    verb = "Short" if direction == "SHORT" else "Buy"
    return {
        "tradingsymbol": fut.tradingsymbol,
        "exchange": "NFO",
        "expiry": fut.expiry.isoformat() if fut.expiry else None,
        "dte": dte,
        "lot_size": lot,
        "ref_price": round(px, 2),
        "contract_value": round(cval, 0),
        "est_margin": round(cval * _MARGIN_PCT, 0),
        "side": side,
        "note": (
            f"{verb} 1 lot ({lot}) of the {fut.expiry.isoformat() if fut.expiry else 'near-month'} "
            f"future — est. margin ~Rs {cval * _MARGIN_PCT:,.0f}. NSE cash has no delivery "
            f"short; roll to the next series 3-4 sessions before expiry. Manage against the "
            f"stock's stop / target."
        ),
    }

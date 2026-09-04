"""Order lifecycle + position / holding / cash book for the paper account.

Fills are modelled at the live last-traded price (no synthetic slippage -
this is a demo account meant to track the real tape). Every fill runs the
Indian statutory cost stack. Equity CNC lands in holdings; equity MIS and
all F&O land in positions with a blocked-margin model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.backtesting.costs import CostModel
from app.config import Settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.paper_account import (
    PaperAccount,
    PaperHolding,
    PaperLedger,
    PaperOrder,
    PaperPosition,
    PaperTrade,
)
from app.paper_account import margin as margin_mod
from app.paper_account import pricing

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_COSTS = CostModel()
_ACCOUNT_LOCK = 776621  # serialize the one-time account creation
_SIDES = {"BUY", "SELL"}
_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
_PRODUCTS = {"CNC", "MIS", "NRML"}


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def _now() -> datetime:
    return datetime.now(UTC)


def first_account(db: Session) -> PaperAccount | None:
    # deterministic: always the oldest row, so the account never appears to
    # "change" between requests even if a stray second row ever exists
    return db.execute(
        select(PaperAccount).order_by(PaperAccount.created_at.asc()).limit(1)
    ).scalar_one_or_none()


def get_or_create_account(db: Session) -> PaperAccount:
    """The single persistent paper account. Its positions, holdings, orders,
    trades and cash book all live in Postgres and survive restarts / reloads."""
    acct = first_account(db)
    if acct is not None:
        return acct
    # a fresh DB gets hit by several parallel requests on first page load;
    # serialize the create so they don't fork the account into duplicates
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ACCOUNT_LOCK})
    acct = first_account(db)
    if acct is None:
        ob = 1_000_000.0
        acct = PaperAccount(opening_balance=ob, cash=0.0, realized_pnl=0.0, charges_paid=0.0)
        db.add(acct)
        db.flush()
        _ledger(db, acct, "FUNDS_ADD", ob, note="Opening balance")  # brings cash 0 -> ob
    db.commit()
    return acct


def _ledger(db: Session, acct: PaperAccount, kind: str, amount: float, *, ref: str | None = None,
            note: str | None = None) -> None:
    acct.cash = float(acct.cash) + amount
    db.add(PaperLedger(account_id=acct.id, at=_now(), kind=kind, amount=amount,
                       balance_after=acct.cash, ref=ref, note=note))


def _segment(asset_class: str, product: str) -> str:
    if asset_class == "OPT":
        return "options"
    if asset_class == "FUT":
        return "futures"
    return "equity_intraday" if product == "MIS" else "equity_delivery"


def _is_holding(asset_class: str, product: str) -> bool:
    return asset_class == "EQUITY" and product == "CNC"


# --------------------------------------------------------------------------
# place / fill
# --------------------------------------------------------------------------

@dataclass
class OrderRequest:
    exchange: str
    tradingsymbol: str
    side: str
    quantity: int
    order_type: str = "MARKET"
    product: str = "CNC"
    price: float | None = None
    trigger_price: float | None = None
    tag: str | None = None


def _validate(req: OrderRequest) -> None:
    if req.side.upper() not in _SIDES:
        raise ValidationError("side must be BUY or SELL")
    if req.order_type.upper() not in _TYPES:
        raise ValidationError("order_type must be MARKET, LIMIT, SL or SL-M")
    if req.product.upper() not in _PRODUCTS:
        raise ValidationError("product must be CNC, MIS or NRML")
    if req.quantity <= 0:
        raise ValidationError("quantity must be positive")
    if req.order_type.upper() in ("LIMIT", "SL") and not req.price:
        raise ValidationError(f"{req.order_type} order needs a price")
    if req.order_type.upper() in ("SL", "SL-M") and not req.trigger_price:
        raise ValidationError(f"{req.order_type} order needs a trigger price")


def place_order(db: Session, settings: Settings, req: OrderRequest) -> PaperOrder:
    _validate(req)
    acct = get_or_create_account(db)
    info = pricing.resolve(db, req.exchange, req.tradingsymbol)
    if info is None:
        raise ValidationError(f"Unknown instrument {req.exchange}:{req.tradingsymbol}")
    product = req.product.upper()
    if info.asset_class != "EQUITY" and product == "CNC":
        product = "NRML"  # F&O can't be CNC
    if info.asset_class == "EQUITY" and product == "NRML":
        product = "CNC"

    q = pricing.one_quote(db, settings, f"{info.exchange}:{info.tradingsymbol}", info.instrument_token)
    ltp = q.ltp

    order = PaperOrder(
        account_id=acct.id, exchange=info.exchange, tradingsymbol=info.tradingsymbol,
        instrument_token=info.instrument_token, segment=info.segment, asset_class=info.asset_class,
        side=req.side.upper(), order_type=req.order_type.upper(), product=product,
        quantity=req.quantity, price=req.price, trigger_price=req.trigger_price,
        status="OPEN", placed_at=_now(), tag=req.tag,
    )
    db.add(order)
    db.flush()

    if order.order_type == "MARKET":
        if ltp is None:
            order.status = "REJECTED"
            order.status_message = "No live price for this instrument right now."
            db.commit()
            return order
        _try_fill(db, acct, order, ltp, q.prev_close)
    else:
        # resting order: a funds pre-check against the limit / trigger price
        ref_px = float(req.price or req.trigger_price or ltp or 0)
        need = _cash_needed(order, ref_px)
        if need > float(acct.cash) + 1e-6:
            order.status = "REJECTED"
            order.status_message = f"Insufficient funds: need ~Rs {need:,.0f}, have Rs {float(acct.cash):,.0f}"
        db.commit()
        return order
    db.commit()
    db.refresh(order)
    return order


def _cash_needed(order: PaperOrder, price: float) -> float:
    """Cash this order will lock when it fills (margin for MIS/F&O, full
    value for CNC / long options), plus a charges cushion."""
    if order.side == "SELL" and _is_holding(order.asset_class, order.product):
        return 0.0  # selling delivered stock frees cash
    m = margin_mod.estimate(
        asset_class=order.asset_class, product=order.product, side=order.side,
        price=price, quantity=order.quantity,
    )
    return m.required + max(20.0, 0.0006 * price * order.quantity)


def _try_fill(db: Session, acct: PaperAccount, order: PaperOrder, price: float,
              prev_close: float | None) -> None:
    need = _cash_needed(order, price)
    if need > float(acct.cash) + 1e-6:
        order.status = "REJECTED"
        order.status_message = (
            f"Insufficient funds: need ~Rs {need:,.0f}, have Rs {float(acct.cash):,.0f}"
        )
        return
    # holding sells / position reduces need an existing lot
    if not _has_inventory_for(db, acct, order):
        order.status = "REJECTED"
        order.status_message = "Nothing to sell / cover for this instrument & product."
        return
    _fill(db, acct, order, price, prev_close)


def _has_inventory_for(db: Session, acct: PaperAccount, order: PaperOrder) -> bool:
    if _is_holding(order.asset_class, order.product):
        if order.side == "BUY":
            return True
        # a demo account allows selling the same day's buy (BTST-style);
        # t1_qty stays informational
        h = _get_holding(db, acct, order)
        return h is not None and h.qty >= order.quantity
    # positions: any BUY or SELL is allowed (SELL opens a short)
    return True


# --------------------------------------------------------------------------
# fill application
# --------------------------------------------------------------------------

def _get_holding(db: Session, acct: PaperAccount, order: PaperOrder) -> PaperHolding | None:
    rows = db.execute(
        select(PaperHolding).where(
            PaperHolding.account_id == acct.id,
            PaperHolding.tradingsymbol == order.tradingsymbol,
            PaperHolding.exchange == order.exchange,
        ).order_by(PaperHolding.created_at.asc())
    ).scalars().all()
    if len(rows) <= 1:
        return rows[0] if rows else None
    return _merge_dupes(db, rows, "qty")  # heal a concurrent double-insert


def _get_position(db: Session, acct: PaperAccount, order: PaperOrder) -> PaperPosition | None:
    rows = db.execute(
        select(PaperPosition).where(
            PaperPosition.account_id == acct.id,
            PaperPosition.tradingsymbol == order.tradingsymbol,
            PaperPosition.product == order.product,
            PaperPosition.status == "OPEN",
        ).order_by(PaperPosition.opened_at.asc())
    ).scalars().all()
    if len(rows) <= 1:
        return rows[0] if rows else None
    return _merge_dupes(db, rows, "net_qty")


def _merge_dupes(db: Session, rows: list, qty_field: str):
    """Fold concurrent duplicate holding/position rows for the same
    instrument into the oldest, summing every numeric column."""
    keep = rows[0]
    numeric = (
        "qty", "t1_qty", "net_qty", "buy_qty", "sell_qty", "buy_value", "sell_value",
        "realized_pnl", "charges", "margin_blocked",
    )
    tot_qty = sum(int(getattr(r, qty_field) or 0) for r in rows)
    cost = sum(float(getattr(r, "avg_price", 0) or 0) * int(getattr(r, qty_field) or 0) for r in rows)
    for f in numeric:
        if hasattr(keep, f):
            setattr(keep, f, sum(float(getattr(r, f) or 0) for r in rows))
    if hasattr(keep, "avg_price"):
        keep.avg_price = round(cost / tot_qty, 4) if tot_qty else float(keep.avg_price)
    for r in rows[1:]:
        db.delete(r)
    db.flush()
    logger.warning("paper_dupe_rows_merged", symbol=keep.tradingsymbol, n=len(rows))
    return keep


def _fill(db: Session, acct: PaperAccount, order: PaperOrder, price: float,
          prev_close: float | None) -> None:
    qty = order.quantity
    value = price * qty
    seg = _segment(order.asset_class, order.product)
    cb = _COSTS.charge(order.side, price, qty, seg, reference_price=price)
    charges = round(cb.statutory_total, 2)

    realized = (
        _apply_holding(db, acct, order, price, prev_close)
        if _is_holding(order.asset_class, order.product)
        else _apply_position(db, acct, order, price, prev_close)
    )
    realized -= charges

    # book the trade
    trade = PaperTrade(
        account_id=acct.id, order_id=order.id, exchange=order.exchange,
        tradingsymbol=order.tradingsymbol, asset_class=order.asset_class, product=order.product,
        side=order.side, quantity=qty, price=price, value=value, charges=charges,
        charges_detail={k: round(v, 2) for k, v in cb.__dict__.items()},
        realized_pnl=round(realized, 2), traded_at=_now(),
    )
    db.add(trade)
    _ledger(db, acct, "CHARGES", -charges, ref=str(order.id), note=f"Charges {order.tradingsymbol}")
    acct.charges_paid = float(acct.charges_paid) + charges
    acct.realized_pnl = float(acct.realized_pnl) + round(realized, 2)

    order.status = "COMPLETE"
    order.filled_qty = qty
    order.avg_fill_price = price
    order.filled_at = _now()
    logger.info("paper_fill", sym=order.tradingsymbol, side=order.side, qty=qty, px=price,
                product=order.product)


def _apply_holding(db: Session, acct: PaperAccount, order: PaperOrder, price: float,
                   prev_close: float | None) -> float:
    h = _get_holding(db, acct, order)
    qty, value = order.quantity, price * order.quantity
    realized = 0.0
    if order.side == "BUY":
        if h is None:
            h = PaperHolding(account_id=acct.id, exchange=order.exchange,
                             tradingsymbol=order.tradingsymbol,
                             instrument_token=order.instrument_token, qty=0, t1_qty=0,
                             avg_price=0, realized_pnl=0)
            db.add(h)
            db.flush()
        new_qty = h.qty + qty
        h.avg_price = (float(h.avg_price) * h.qty + value) / new_qty if new_qty else 0.0
        h.qty = new_qty
        h.t1_qty += qty
        _ledger(db, acct, "BUY", -value, ref=str(order.id),
                note=f"Buy {qty} {order.tradingsymbol} @ {price:.2f}")
    else:  # SELL delivered stock
        assert h is not None  # guaranteed by _has_inventory_for  # noqa: S101
        realized = (price - float(h.avg_price)) * qty
        h.qty -= qty
        h.t1_qty = min(h.t1_qty, h.qty)
        h.realized_pnl = float(h.realized_pnl) + realized
        _ledger(db, acct, "SELL", value, ref=str(order.id),
                note=f"Sell {qty} {order.tradingsymbol} @ {price:.2f}")
        if h.qty <= 0:
            db.delete(h)
    if h is not None and h.qty > 0:
        h.last_price = price
        h.prev_close = prev_close or h.prev_close
    return realized


def _apply_position(db: Session, acct: PaperAccount, order: PaperOrder, price: float,
                    prev_close: float | None) -> float:
    p = _get_position(db, acct, order)
    signed = order.quantity if order.side == "BUY" else -order.quantity
    if p is None:
        p = PaperPosition(
            account_id=acct.id, exchange=order.exchange, tradingsymbol=order.tradingsymbol,
            instrument_token=order.instrument_token, segment=order.segment,
            asset_class=order.asset_class, product=order.product,
            net_qty=0, avg_price=0.0, day=order.product == "MIS",
            opened_at=_now(), trading_day=_today_ist(), status="OPEN",
        )
        db.add(p)
        db.flush()

    realized = 0.0
    old_net = p.net_qty
    if order.side == "BUY":
        p.buy_qty += order.quantity
        p.buy_value = float(p.buy_value) + price * order.quantity
    else:
        p.sell_qty += order.quantity
        p.sell_value = float(p.sell_value) + price * order.quantity

    if old_net == 0 or (old_net > 0) == (signed > 0):
        # opening or adding to the same side
        total = abs(old_net) + order.quantity
        p.avg_price = (float(p.avg_price) * abs(old_net) + price * order.quantity) / total
        p.net_qty = old_net + signed
        m = margin_mod.estimate(asset_class=order.asset_class, product=order.product,
                                side=order.side, price=price, quantity=order.quantity)
        p.margin_blocked = float(p.margin_blocked) + m.required
        _ledger(db, acct, "BUY" if order.side == "BUY" else "SELL", -m.required, ref=str(order.id),
                note=f"{order.side} {order.quantity} {order.tradingsymbol} @ {price:.2f} (margin)")
    else:
        # reducing / closing / flipping
        closing = min(order.quantity, abs(old_net))
        direction = 1.0 if old_net > 0 else -1.0
        realized = closing * (price - float(p.avg_price)) * direction
        released = float(p.margin_blocked) * (closing / abs(old_net)) if old_net else 0.0
        p.margin_blocked = float(p.margin_blocked) - released
        p.realized_pnl = float(p.realized_pnl) + realized
        p.net_qty = old_net + signed
        _ledger(db, acct, "SELL" if order.side == "SELL" else "BUY", released + realized,
                ref=str(order.id),
                note=f"{order.side} {order.quantity} {order.tradingsymbol} @ {price:.2f} "
                     f"(close, P&L {realized:+.0f})")
        if p.net_qty != 0 and (p.net_qty > 0) != (old_net > 0):
            # flipped: the remainder opened a fresh position at this price
            rem = abs(p.net_qty)
            p.avg_price = price
            m = margin_mod.estimate(asset_class=order.asset_class, product=order.product,
                                    side=order.side, price=price, quantity=rem)
            p.margin_blocked = float(p.margin_blocked) + m.required
            _ledger(db, acct, order.side, -m.required, ref=str(order.id), note="flip open (margin)")

    p.last_price = price
    p.prev_close = prev_close or p.prev_close
    if p.net_qty == 0:
        p.status = "CLOSED"
        p.closed_at = _now()
    return realized


# --------------------------------------------------------------------------
# order management
# --------------------------------------------------------------------------

def cancel_order(db: Session, order_id: str) -> PaperOrder:
    order = db.get(PaperOrder, order_id)
    if order is None:
        raise ValidationError("order not found")
    if order.status != "OPEN":
        raise ValidationError(f"cannot cancel a {order.status} order")
    order.status = "CANCELLED"
    order.status_message = "Cancelled by user"
    db.commit()
    return order


def retry_order(db: Session, settings: Settings, order_id: str) -> PaperOrder:
    """Re-submit a rejected / cancelled order as a fresh order with the
    same parameters (a new row — the original stays as history)."""
    old = db.get(PaperOrder, order_id)
    if old is None:
        raise ValidationError("order not found")
    if old.status not in ("REJECTED", "CANCELLED"):
        raise ValidationError(
            f"only a rejected or cancelled order can be retried (this one is {old.status})"
        )
    return place_order(db, settings, OrderRequest(
        exchange=old.exchange, tradingsymbol=old.tradingsymbol,
        side=old.side, quantity=old.quantity, order_type=old.order_type,
        product=old.product,
        price=float(old.price) if old.price is not None else None,
        trigger_price=float(old.trigger_price) if old.trigger_price is not None else None,
        tag=old.tag,
    ))


def modify_order(db: Session, order_id: str, *, price: float | None = None,
                 trigger_price: float | None = None, quantity: int | None = None) -> PaperOrder:
    order = db.get(PaperOrder, order_id)
    if order is None:
        raise ValidationError("order not found")
    if order.status != "OPEN":
        raise ValidationError(f"cannot modify a {order.status} order")
    if price is not None:
        order.price = price
    if trigger_price is not None:
        order.trigger_price = trigger_price
    if quantity is not None and quantity > 0:
        order.quantity = quantity
    db.commit()
    return order


def exit_position(db: Session, settings: Settings, position_id: str) -> PaperOrder:
    p = db.get(PaperPosition, position_id)
    if p is None or p.status != "OPEN" or p.net_qty == 0:
        raise ValidationError("position not open")
    return place_order(db, settings, OrderRequest(
        exchange=p.exchange, tradingsymbol=p.tradingsymbol,
        side="SELL" if p.net_qty > 0 else "BUY", quantity=abs(p.net_qty),
        order_type="MARKET", product=p.product, tag="exit",
    ))


def add_funds(db: Session, amount: float) -> PaperAccount:
    if amount == 0:
        raise ValidationError("amount must be non-zero")
    acct = get_or_create_account(db)
    _ledger(db, acct, "FUNDS_ADD", amount, note="Manual funds adjustment")
    db.commit()
    return acct


def reset_account(db: Session, *, opening_balance: float | None = None) -> PaperAccount:
    acct = get_or_create_account(db)
    for model in (PaperTrade, PaperOrder, PaperPosition, PaperHolding, PaperLedger):
        db.query(model).filter(model.account_id == acct.id).delete()
    ob = opening_balance if opening_balance and opening_balance > 0 else float(acct.opening_balance)
    acct.opening_balance = ob
    acct.cash = 0.0
    acct.realized_pnl = 0.0
    acct.charges_paid = 0.0
    acct.last_eod_day = None
    db.flush()
    _ledger(db, acct, "FUNDS_ADD", ob, note="Account reset - opening balance")  # cash 0 -> ob
    db.commit()
    return acct

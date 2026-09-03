"""Read/serialise layer for the paper account API. Marks positions and
holdings to the live price on every read."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.paper_account import (
    PaperHolding,
    PaperLedger,
    PaperOrder,
    PaperPosition,
    PaperTrade,
)
from app.paper_account import pricing
from app.paper_account.engine import get_or_create_account


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _price_map(db: Session, settings: Settings,
               rows: Sequence[PaperPosition | PaperHolding]) -> dict[str, pricing.Quote]:
    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        ref = f"{r.exchange}:{r.tradingsymbol}"
        seen.setdefault(ref, {"ref": ref, "token": r.instrument_token})
    return pricing.quotes(db, settings, list(seen.values())) if seen else {}


def _pos_dict(p: PaperPosition, q: pricing.Quote | None) -> dict[str, Any]:
    ltp = q.ltp if q and q.ltp is not None else _f(p.last_price)
    avg = _f(p.avg_price)
    unrealized = p.net_qty * (ltp - avg) if ltp else 0.0
    pnl = _f(p.realized_pnl) + unrealized
    prev = q.prev_close if q and q.prev_close else _f(p.prev_close) or avg
    return {
        "id": str(p.id),
        "exchange": p.exchange, "tradingsymbol": p.tradingsymbol, "segment": p.segment,
        "asset_class": p.asset_class, "product": p.product,
        "net_qty": p.net_qty, "buy_qty": p.buy_qty, "sell_qty": p.sell_qty,
        "avg_price": round(avg, 2),
        "ltp": round(ltp, 2) if ltp else None,
        "prev_close": round(prev, 2) if prev else None,
        "day_change_pct": round((ltp - prev) / prev * 100, 2) if ltp and prev else None,
        "realized_pnl": round(_f(p.realized_pnl), 2),
        "unrealized_pnl": round(unrealized, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / (avg * abs(p.net_qty)) * 100, 2) if avg and p.net_qty else None,
        "margin_blocked": round(_f(p.margin_blocked), 2),
        "value": round(abs(p.net_qty) * ltp, 2) if ltp else None,
        "day": p.day, "status": p.status,
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
    }


def _hold_dict(h: PaperHolding, q: pricing.Quote | None) -> dict[str, Any]:
    ltp = q.ltp if q and q.ltp is not None else _f(h.last_price)
    avg = _f(h.avg_price)
    prev = q.prev_close if q and q.prev_close else _f(h.prev_close) or avg
    invested = h.qty * avg
    cur = h.qty * ltp if ltp else invested
    return {
        "id": str(h.id),
        "exchange": h.exchange, "tradingsymbol": h.tradingsymbol,
        "qty": h.qty, "t1_qty": h.t1_qty, "avg_price": round(avg, 2),
        "ltp": round(ltp, 2) if ltp else None,
        "prev_close": round(prev, 2) if prev else None,
        "invested": round(invested, 2),
        "current_value": round(cur, 2),
        "pnl": round(cur - invested, 2),
        "pnl_pct": round((cur - invested) / invested * 100, 2) if invested else None,
        "day_pnl": round(h.qty * (ltp - prev), 2) if ltp and prev else None,
        "day_change_pct": round((ltp - prev) / prev * 100, 2) if ltp and prev else None,
    }


def _order_dict(o: PaperOrder) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "placed_at": o.placed_at.isoformat() if o.placed_at else None,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        "exchange": o.exchange, "tradingsymbol": o.tradingsymbol, "asset_class": o.asset_class,
        "side": o.side, "order_type": o.order_type, "product": o.product,
        "quantity": o.quantity, "filled_qty": o.filled_qty,
        "price": _f(o.price) or None, "trigger_price": _f(o.trigger_price) or None,
        "avg_fill_price": _f(o.avg_fill_price) or None,
        "status": o.status, "status_message": o.status_message,
        "is_squareoff": o.is_squareoff, "tag": o.tag,
    }


def _trade_dict(t: PaperTrade) -> dict[str, Any]:
    return {
        "id": str(t.id), "order_id": str(t.order_id),
        "traded_at": t.traded_at.isoformat() if t.traded_at else None,
        "exchange": t.exchange, "tradingsymbol": t.tradingsymbol, "asset_class": t.asset_class,
        "product": t.product, "side": t.side, "quantity": t.quantity,
        "price": round(_f(t.price), 2), "value": round(_f(t.value), 2),
        "charges": round(_f(t.charges), 2), "charges_detail": t.charges_detail,
        "realized_pnl": round(_f(t.realized_pnl), 2),
    }


def summary(db: Session, settings: Settings) -> dict[str, Any]:
    acct = get_or_create_account(db)
    positions = list(db.execute(
        select(PaperPosition).where(PaperPosition.account_id == acct.id, PaperPosition.status == "OPEN")
    ).scalars().all())
    holdings = list(db.execute(
        select(PaperHolding).where(PaperHolding.account_id == acct.id, PaperHolding.qty > 0)
    ).scalars().all())
    qmap = _price_map(db, settings, [*positions, *holdings])

    pos_rows = [_pos_dict(p, qmap.get(f"{p.exchange}:{p.tradingsymbol}")) for p in positions]
    hold_rows = [_hold_dict(h, qmap.get(f"{h.exchange}:{h.tradingsymbol}")) for h in holdings]
    # persist the marked LTPs
    for p, r in zip(positions, pos_rows, strict=True):
        if r["ltp"]:
            p.last_price = r["ltp"]
            p.prev_close = r["prev_close"]
    for h, r in zip(holdings, hold_rows, strict=True):
        if r["ltp"]:
            h.last_price = r["ltp"]
            h.prev_close = r["prev_close"]
    db.commit()

    used_margin = sum(r["margin_blocked"] for r in pos_rows)
    pos_unreal = sum(r["unrealized_pnl"] for r in pos_rows)
    hold_value = sum(r["current_value"] for r in hold_rows)
    hold_unreal = sum(r["pnl"] for r in hold_rows)
    hold_day = sum(r["day_pnl"] or 0 for r in hold_rows)
    cash = _f(acct.cash)

    funds_added = _f(db.execute(
        select(func.coalesce(func.sum(PaperLedger.amount), 0.0)).where(
            PaperLedger.account_id == acct.id, PaperLedger.kind == "FUNDS_ADD"
        )
    ).scalar_one())
    invested_capital = funds_added  # opening balance is logged as a FUNDS_ADD too
    net_worth = cash + used_margin + pos_unreal + hold_value
    total_pnl = net_worth - invested_capital

    return {
        "account": {
            "name": acct.name,
            "opening_balance": _f(acct.opening_balance),
            "invested_capital": round(invested_capital, 2),
            "auto_squareoff_mis": acct.auto_squareoff_mis,
        },
        "funds": {
            "available_margin": round(cash, 2),
            "used_margin": round(used_margin, 2),
            "total_margin": round(cash + used_margin, 2),
        },
        "pnl": {
            "booked": round(_f(acct.realized_pnl), 2),
            "positions_unrealized": round(pos_unreal, 2),
            "holdings_unrealized": round(hold_unreal, 2),
            "holdings_day": round(hold_day, 2),
            "total": round(total_pnl, 2),
            "total_pct": round(total_pnl / invested_capital * 100, 2) if invested_capital else None,
        },
        "charges_paid": round(_f(acct.charges_paid), 2),
        "net_worth": round(net_worth, 2),
        "holdings_value": round(hold_value, 2),
        "counts": {
            "positions": len(pos_rows),
            "holdings": len(hold_rows),
            "open_orders": db.execute(
                select(func.count()).select_from(PaperOrder).where(
                    PaperOrder.account_id == acct.id, PaperOrder.status == "OPEN"
                )
            ).scalar_one(),
        },
    }


def positions(db: Session, settings: Settings, *, include_closed: bool = False) -> list[dict[str, Any]]:
    acct = get_or_create_account(db)
    stmt = select(PaperPosition).where(PaperPosition.account_id == acct.id)
    if not include_closed:
        stmt = stmt.where(PaperPosition.status == "OPEN")
    rows = list(db.execute(stmt.order_by(PaperPosition.opened_at.desc())).scalars().all())
    qmap = _price_map(db, settings, rows)
    return [_pos_dict(p, qmap.get(f"{p.exchange}:{p.tradingsymbol}")) for p in rows]


def holdings(db: Session, settings: Settings) -> list[dict[str, Any]]:
    acct = get_or_create_account(db)
    rows = list(db.execute(
        select(PaperHolding).where(PaperHolding.account_id == acct.id, PaperHolding.qty > 0)
        .order_by(PaperHolding.tradingsymbol)
    ).scalars().all())
    qmap = _price_map(db, settings, rows)
    return [_hold_dict(h, qmap.get(f"{h.exchange}:{h.tradingsymbol}")) for h in rows]


def orders(db: Session, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    acct = get_or_create_account(db)
    stmt = select(PaperOrder).where(PaperOrder.account_id == acct.id)
    if status:
        stmt = stmt.where(PaperOrder.status == status.upper())
    rows = db.execute(stmt.order_by(PaperOrder.placed_at.desc()).limit(limit)).scalars().all()
    return [_order_dict(o) for o in rows]


def trades(db: Session, *, limit: int = 300) -> list[dict[str, Any]]:
    acct = get_or_create_account(db)
    rows = db.execute(
        select(PaperTrade).where(PaperTrade.account_id == acct.id)
        .order_by(PaperTrade.traded_at.desc()).limit(limit)
    ).scalars().all()
    return [_trade_dict(t) for t in rows]


def ledger(db: Session, *, limit: int = 300) -> list[dict[str, Any]]:
    acct = get_or_create_account(db)
    rows = db.execute(
        select(PaperLedger).where(PaperLedger.account_id == acct.id)
        .order_by(PaperLedger.at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": str(r.id), "at": r.at.isoformat() if r.at else None, "kind": r.kind,
            "amount": round(_f(r.amount), 2), "balance_after": round(_f(r.balance_after), 2),
            "ref": r.ref, "note": r.note,
        }
        for r in rows
    ]


def instrument_for_order(db: Session, settings: Settings, exchange: str, tradingsymbol: str) -> dict[str, Any]:
    info = pricing.resolve(db, exchange, tradingsymbol)
    if info is None:
        return {"found": False, "reason": f"Unknown instrument {exchange}:{tradingsymbol}"}
    q = pricing.one_quote(db, settings, f"{info.exchange}:{info.tradingsymbol}", info.instrument_token)
    return {
        "found": True,
        "exchange": info.exchange, "tradingsymbol": info.tradingsymbol,
        "name": info.name, "segment": info.segment, "asset_class": info.asset_class,
        "lot_size": info.lot_size, "tick_size": info.tick_size,
        "ltp": round(q.ltp, 2) if q.ltp else None,
        "prev_close": round(q.prev_close, 2) if q.prev_close else None,
    }

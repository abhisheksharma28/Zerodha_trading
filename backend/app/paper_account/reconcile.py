"""Rebuild the paper account's cash + holdings + positions from the
authoritative PaperTrade log.

Needed because a concurrency bug in basket deploy (two rebalances racing)
could double-apply a fill: the trade row was still written once per
COMPLETE order (1:1, clean), but ``acct.cash`` and the holding rows drifted.
This recomputes everything from the trades so the account reflects reality
without wiping the forward-testing history.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.paper_account import (
    PaperAccount,
    PaperHolding,
    PaperLedger,
    PaperPosition,
    PaperTrade,
)
from app.paper_account.engine import _is_holding, _now, first_account

logger = get_logger(__name__)


def _rebuild_holdings(db: Session, acct: PaperAccount, trades: list[PaperTrade]) -> float:
    """Rebuild every CNC/EQUITY-delivery holding from its trades. Returns the
    net cash effect of all holding trades."""
    by_sym: dict[str, list[PaperTrade]] = {}
    for t in trades:
        if _is_holding(t.asset_class, t.product):
            by_sym.setdefault(f"{t.exchange}:{t.tradingsymbol}", []).append(t)

    existing: dict[str, list[PaperHolding]] = {}
    for h in db.execute(
        select(PaperHolding)
        .where(PaperHolding.account_id == acct.id)
        .order_by(PaperHolding.created_at.asc())
    ).scalars().all():
        existing.setdefault(f"{h.exchange}:{h.tradingsymbol}", []).append(h)

    cash_effect = 0.0
    touched: set[str] = set()

    for ref, ts in by_sym.items():
        ts.sort(key=lambda t: t.traded_at)
        qty = 0
        basis = 0.0            # total cost of the open lot
        realized = 0.0
        ex, sym = ref.split(":", 1)
        for t in ts:
            v, c = float(t.value), float(t.charges)
            if t.side == "BUY":
                qty += t.quantity
                basis += v
                cash_effect -= v + c
            else:  # SELL
                avg = basis / qty if qty else 0.0
                realized += (float(t.price) - avg) * t.quantity - c
                basis -= avg * min(t.quantity, qty)
                qty -= t.quantity
                cash_effect += v - c
        touched.add(ref)

        rows = existing.get(ref, [])
        for extra in rows[1:]:            # collapse any duplicate rows
            db.delete(extra)
        h = rows[0] if rows else None
        if qty > 0:
            avg = round(basis / qty, 4)
            if h is None:
                h = PaperHolding(
                    account_id=acct.id, exchange=ex, tradingsymbol=sym,
                    instrument_token=None, qty=0, t1_qty=0, avg_price=0, realized_pnl=0,
                )
                db.add(h)
            h.qty = qty
            h.t1_qty = min(int(h.t1_qty or 0), qty)
            h.avg_price = avg
            h.realized_pnl = round(realized, 2)
        elif h is not None:
            db.delete(h)

    # drop any holding rows with no trades at all (pure phantom)
    for ref, rows in existing.items():
        if ref not in touched:
            for h in rows:
                db.delete(h)
    return cash_effect


def _position_cash_effect(db: Session, acct: PaperAccount, trades: list[PaperTrade]) -> float:
    """Net cash effect of all MIS / F&O activity, WITHOUT touching the
    position rows (baskets are CNC-only, so positions aren't corrupted).

    = Σ realised P&L booked on position trades − margin still blocked on
      the currently-open positions.
    """
    realized = sum(
        float(t.realized_pnl) for t in trades
        if not _is_holding(t.asset_class, t.product)
    )
    blocked = sum(
        float(m or 0) for m in db.execute(
            select(PaperPosition.margin_blocked).where(
                PaperPosition.account_id == acct.id, PaperPosition.status == "OPEN"
            )
        ).scalars().all()
    )
    return realized - blocked


def reconcile(db: Session) -> dict[str, Any]:
    acct = first_account(db)
    if acct is None:
        return {"reconciled": False, "reason": "no paper account"}

    trades = list(
        db.execute(
            select(PaperTrade).where(PaperTrade.account_id == acct.id)
        ).scalars().all()
    )
    extra_funds = db.execute(
        select(PaperLedger).where(
            PaperLedger.account_id == acct.id, PaperLedger.kind == "FUNDS_ADD"
        ).order_by(PaperLedger.at.asc())
    ).scalars().all()
    # the first FUNDS_ADD is the opening balance; the rest are manual top-ups
    manual_adds = sum(float(f.amount) for f in extra_funds[1:]) if len(extra_funds) > 1 else 0.0
    opening = float(acct.opening_balance)

    old_cash = float(acct.cash)
    holding_cash = _rebuild_holdings(db, acct, trades)
    position_cash = _position_cash_effect(db, acct, trades)
    new_cash = round(opening + manual_adds + holding_cash + position_cash, 2)

    acct.cash = new_cash
    acct.realized_pnl = round(sum(float(t.realized_pnl) for t in trades), 2)
    acct.charges_paid = round(sum(float(t.charges) for t in trades), 2)

    delta = round(new_cash - old_cash, 2)
    if abs(delta) > 0.01:
        db.add(PaperLedger(
            account_id=acct.id, at=_now(), kind="RECONCILE", amount=delta,
            balance_after=new_cash,
            note=f"Reconciled cash from the trade log (was Rs {old_cash:,.0f}).",
        ))
    db.commit()

    logger.info("paper_account_reconciled", old_cash=old_cash, new_cash=new_cash, delta=delta)
    return {
        "reconciled": True,
        "old_cash": round(old_cash, 2),
        "new_cash": new_cash,
        "delta": delta,
        "trades_replayed": len(trades),
        "note": (
            "Cash and holdings were rebuilt from the trade log. A negative or low "
            "balance means the account is genuinely over-committed (a past bug let it "
            "over-buy) — sell some positions, add funds, or Reset for a clean slate."
        ) if new_cash < opening * 0.1 else "Account reconciled cleanly.",
    }

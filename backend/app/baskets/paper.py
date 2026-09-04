"""Deploy a basket into the standalone paper account and keep it
rebalanced on its cadence.

A deployed basket owns a notional ``capital``. Everything it holds is
tracked from its own tagged orders (``basket:<id>``) — never mixed with
manual trades or other baskets. Its portfolio value at any moment is::

    basket_cash + Σ tagged_net_qty[s] * price[s]

where ``basket_cash = capital + Σ (sell proceeds − buy cost − charges)``
over its tagged fills.

Orders are CNC market orders routed through ``paper_account.engine``.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtesting.adhoc import fetch_candles
from app.baskets.backtest import _warmup_bars
from app.baskets.engine import _as_dt, plan_orders, resolve_targets
from app.baskets.spec import SpecError, parse_spec
from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.basket import Basket, BasketRebalanceEvent
from app.models.paper_account import PaperOrder, PaperTrade
from app.paper_account import engine as pa_engine
from app.paper_account import pricing
from app.paper_account.engine import OrderRequest, get_or_create_account

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_EXCHANGE = "NSE"

# _do_rebalance places orders off the current drift and is NOT idempotent,
# so serialise it: the deploy call and a racing scheduler tick must never
# rebalance the same basket at the same time.
_rebalance_gate = threading.Lock()


def _tag(basket_id) -> str:
    return f"basket:{basket_id}"


def _inr(v: float) -> str:
    a = abs(v)
    if a >= 1e7:
        return f"₹{v / 1e7:.2f} Cr"
    if a >= 1e5:
        return f"₹{v / 1e5:.2f} L"
    return f"₹{v:,.0f}"


def _get(db: Session, basket_id: str) -> Basket:
    try:
        bid = uuid.UUID(str(basket_id))
    except ValueError as exc:
        raise NotFoundError("basket not found") from exc
    b = db.get(Basket, bid)
    if b is None:
        raise NotFoundError("basket not found")
    return b


def _spec_of(b: Basket):
    try:
        return parse_spec(b.spec)
    except SpecError as exc:
        raise ValidationError(f"basket spec is invalid: {exc}") from exc


def _tagged_state(db: Session, account_id, basket_id) -> tuple[dict[str, int], float]:
    """(-> net qty per tradingsymbol, -> basket cash flow from tagged fills)."""
    tag = _tag(basket_id)
    rows = db.execute(
        select(PaperOrder.tradingsymbol, PaperOrder.side, func.sum(PaperOrder.filled_qty))
        .where(
            PaperOrder.account_id == account_id,
            PaperOrder.tag == tag,
            PaperOrder.status == "COMPLETE",
        )
        .group_by(PaperOrder.tradingsymbol, PaperOrder.side)
    ).all()
    net: dict[str, int] = {}
    for sym, side, qty in rows:
        net[sym] = net.get(sym, 0) + (int(qty) if side == "BUY" else -int(qty))
    net = {s: q for s, q in net.items() if q != 0}

    flow_rows = db.execute(
        select(PaperTrade.side, PaperTrade.value, PaperTrade.charges)
        .join(PaperOrder, PaperOrder.id == PaperTrade.order_id)
        .where(PaperOrder.tag == tag)
    ).all()
    cash_flow = 0.0
    for side, value, charges in flow_rows:
        v, c = float(value), float(charges)
        cash_flow += (v - c) if side == "SELL" else -(v + c)
    return net, cash_flow


def _history(db: Session, settings: Settings, spec, *, extra: tuple[str, ...] = ()):
    warmup = _warmup_bars(spec)
    days = int(warmup * 1.6) + 40
    end = datetime.now().date()
    start = end.fromordinal(end.toordinal() - days)
    want_syms = list(dict.fromkeys([*spec.symbols, *extra]))
    candles, skipped = fetch_candles(
        db, settings, symbols=want_syms, timeframe="1d",
        start=start.isoformat(), end=end.isoformat(),
    )
    bars_by_symbol: dict[str, list] = {}
    for want in want_syms:
        for got, bars in candles.items():
            if got.upper() == want.upper():
                bars_by_symbol[want] = bars
                break
    return bars_by_symbol, skipped


def _prices(db: Session, settings: Settings, refs: list[str], hist: dict[str, list]) -> dict[str, float]:
    resolved: list[dict] = []
    for sym in refs:
        info = pricing.resolve(db, _EXCHANGE, sym)
        resolved.append({"ref": f"{_EXCHANGE}:{sym}", "token": info.instrument_token if info else None})
    q = pricing.quotes(db, settings, resolved)
    out: dict[str, float] = {}
    for sym in refs:
        quote = q.get(f"{_EXCHANGE}:{sym}")
        px = quote.ltp if quote and quote.ltp else None
        if px is None:  # market closed / not subscribed -> last daily close
            bars = hist.get(sym)
            if bars:
                px = float(bars[-1].close)
        if px:
            out[sym] = float(px)
    return out


def unit_cost_for_spec(db: Session, settings: Settings, spec) -> dict:
    """Roughly the capital needed to hold one share of every name the basket
    actually holds — NOT one share of the whole research universe.

    For each sleeve we take the number of names it will hold (``top_k`` /
    hold buffer for a ruled sleeve, all members for a static one) and add
    ``avg_member_price * k``. Static ETF sleeves contribute one share each.

    Deploying N "units" allocates ``unit_cost * N`` across the sleeves.
    """
    try:
        hist, _ = _history(db, settings, spec)
    except Exception:  # noqa: BLE001 - a price lookup must not hard-fail the caller
        hist = {}
    refs = list(spec.symbols)
    prices = _prices(db, settings, refs, hist)
    per = {s: round(prices[s], 2) for s in refs if s in prices}
    missing = [s for s in refs if s not in per]

    need = 0.0
    est_holdings = 0
    for sl in spec.sleeves:
        priced = [per[m] for m in sl.members if m in per]
        if not priced or sl.weight <= 0:
            continue
        rule = sl.rule
        k = rule.effective_hold_k if getattr(rule, "active", False) else len(sl.members)
        k = max(1, min(k, len(priced)))
        est_holdings += k
        # one share of each of the ~k names the sleeve actually holds, using
        # the average member price as the estimate of which k get picked
        need += (sum(priced) / len(priced)) * k

    unit_cost = round(need) if need > 0 else round(sum(per.values()), 2)
    return {
        "unit_cost": round(unit_cost, 2),
        "per_symbol": per,
        "missing": missing,
        "n_members": len(refs),
        "n_priced": len(per),
        "est_holdings": est_holdings,
        "as_of": datetime.now(UTC).isoformat(),
    }


def deploy_preview(db: Session, settings: Settings, basket_id: str) -> dict:
    """What a deploy would cost right now, and how many "units" the paper
    account can currently afford. Drives the units stepper in the deploy UI."""
    b = _get(db, basket_id)
    spec = _spec_of(b)
    acct = get_or_create_account(db)
    uc = unit_cost_for_spec(db, settings, spec)
    unit = float(uc["unit_cost"])
    have = float(acct.cash)
    max_units = int(have // unit) if unit > 0 else 0
    cur = float(b.capital)
    want_units = max(1, round(cur / unit)) if unit > 0 else 1
    # clamp the stepper's opening value to what the account can actually fund;
    # if it can't afford even one unit, start at the minimum and let the UI warn
    suggested = min(want_units, max_units) if max_units > 0 else 1
    return {
        "basket_id": str(b.id),
        "name": b.name,
        "status": b.status,
        "unit_cost": round(unit, 2),
        "per_symbol": uc["per_symbol"],
        "missing": uc["missing"],
        "n_members": uc["n_members"],
        "n_priced": uc["n_priced"],
        "est_holdings": uc.get("est_holdings"),
        "available_cash": round(have, 2),
        "max_units": max_units,
        "current_capital": round(cur, 2),
        "suggested_units": suggested,
    }


def _fundamentals_fn(settings: Settings):
    """symbol -> {value, quality, growth} in 0..100, from the scanner's
    present-day fundamentals view. Cached per call so a rebalance hits each
    name once. Live / paper only — never used in a historical backtest."""
    from app.market_scanner import fundamentals as fmod

    cache: dict[str, dict[str, float] | None] = {}

    def _fn(symbol: str) -> dict[str, float] | None:
        if symbol in cache:
            return cache[symbol]
        try:
            v = fmod.view(settings, symbol)
        except Exception:  # noqa: BLE001 - a missing name must not break the rebalance
            cache[symbol] = None
            return None
        out = None
        if v and v.available:
            out = {}
            if v.valuation is not None:
                out["value"] = float(v.valuation)
            if v.quality is not None:
                out["quality"] = float(v.quality)
            if v.growth is not None:
                out["growth"] = float(v.growth)
        cache[symbol] = out
        return out

    return _fn


def _period_tag(dt: datetime, freq: str) -> tuple:
    if freq == "weekly":
        iso = dt.isocalendar()
        return ("w", iso[0], iso[1])
    if freq == "quarterly":
        return ("q", dt.year, (dt.month - 1) // 3)
    return ("m", dt.year, dt.month)


def _is_due(b: Basket, now_ist: datetime) -> bool:
    if b.last_rebalanced_at is None:
        return True
    last = b.last_rebalanced_at.astimezone(IST)
    return _period_tag(last, b.rebalance_frequency) != _period_tag(now_ist, b.rebalance_frequency)


def _do_rebalance(
    db: Session, settings: Settings, b: Basket, *, applied: bool, reason: str,
    require_due: bool = False,
) -> dict:
    if not applied:
        return _do_rebalance_locked(db, settings, b, applied=False, reason=reason)
    with _rebalance_gate:
        db.refresh(b)  # pick up a rebalance another thread just finished
        if require_due and not _is_due(b, datetime.now(IST)):
            return {
                "basket_id": str(b.id), "applied": False, "skipped": True,
                "reason": "not due (another rebalance just ran)",
            }
        return _do_rebalance_locked(db, settings, b, applied=True, reason=reason)


def _do_rebalance_locked(
    db: Session, settings: Settings, b: Basket, *, applied: bool, reason: str
) -> dict:
    spec = _spec_of(b)
    acct = get_or_create_account(db)
    net, cash_flow = _tagged_state(db, acct.id, b.id)
    basket_cash = float(b.capital) + cash_flow

    bench = (b.benchmark or "").strip()
    hist, skipped = _history(db, settings, spec, extra=(bench,) if bench else ())
    if not hist:
        raise ValidationError("no price history for the basket members right now")

    now = datetime.now(UTC)
    needs_fundamentals = any(s.rule.uses_fundamentals for s in spec.sleeves)
    fn = _fundamentals_fn(settings) if needs_fundamentals else None
    targets = resolve_targets(
        spec, hist, _as_dt(now.replace(tzinfo=None)),
        current_holdings=net, fundamentals_fn=fn,
        market_bars=hist.get(bench) if bench else None,
    )
    refs = list(dict.fromkeys([*spec.symbols, *net.keys()]))
    prices = _prices(db, settings, refs, hist)

    invested_value = sum(net.get(s, 0) * prices.get(s, 0.0) for s in net)
    pv = basket_cash + invested_value
    if pv <= 0:
        raise ValidationError("basket portfolio value is zero — check prices / capital")

    reasons: dict[str, str] = {}
    for sym in set(targets.weights) | set(net):
        sc = targets.score_of(sym)
        if sym in targets.weights and sym not in net:
            reasons[sym] = (
                f"added — composite score {sc:.0f}/100" if sc is not None else "added — cleared the rule"
            )
        elif sym in net and sym not in targets.weights:
            reasons[sym] = (
                f"removed — score {sc:.0f}/100 below the hold buffer" if sc is not None
                else "removed — fell below the rank / trend gate"
            )
    intents = plan_orders(
        targets.weights, net, prices, pv,
        drift_band_pct=float(b.drift_band_pct), reasons=reasons,
    )

    placed = 0
    if applied:
        for it in intents:
            try:
                pa_engine.place_order(
                    db, settings,
                    OrderRequest(
                        exchange=_EXCHANGE, tradingsymbol=it.symbol, side=it.side,
                        quantity=it.qty, order_type="MARKET", product="CNC", tag=_tag(b.id),
                    ),
                )
                placed += 1
            except ValidationError as exc:
                logger.warning("basket_order_rejected", basket=str(b.id), symbol=it.symbol, err=str(exc))
        b.last_rebalanced_at = now
        b.status = "deployed"

    ev = BasketRebalanceEvent(
        basket_id=b.id,
        as_of=now,
        mode="paper" if applied else "preview",
        target_weights={k: round(v, 4) for k, v in targets.weights.items()},
        orders=[it.to_dict() for it in intents],
        applied=applied,
        note=f"{reason} — {placed}/{len(intents)} orders placed"
        if applied
        else f"{reason} — {len(intents)} orders planned",
    )
    db.add(ev)
    db.commit()

    return {
        "basket_id": str(b.id),
        "as_of": now.isoformat(),
        "applied": applied,
        "portfolio_value": round(pv, 2),
        "basket_cash": round(basket_cash, 2),
        "target_weights": ev.target_weights,
        "orders": ev.orders,
        "orders_placed": placed,
        "notes": targets.notes,
        "risk_contribution": targets.risk_contribution,
        "skipped": skipped,
    }


def deploy(
    db: Session, settings: Settings, basket_id: str, *, capital: float | None = None
) -> dict:
    b = _get(db, basket_id)
    _spec_of(b)  # validate
    if b.status == "deployed":
        raise ValidationError("basket is already deployed")
    acct = get_or_create_account(db)

    # an optional deploy size (e.g. N "units" = N * one-share-of-each) overrides
    # the basket's stored capital and is persisted so status / rebalance / P&L
    # all measure against what was actually deployed.
    if capital is not None:
        capital = float(capital)
        if capital < 500.0:
            raise ValidationError("deploy size must be at least ₹500")
        b.capital = capital

    # a deployed basket buys ~its `capital` worth of stock out of the paper
    # account's REAL free cash. Refuse (don't half-fill) if it can't be
    # funded, so the account can't silently over-commit across baskets.
    want = float(b.capital)
    have = float(acct.cash)
    if want > have + 1.0:
        raise ValidationError(
            f"This basket needs {_inr(want)} but the paper account has only "
            f"{_inr(have)} free. Lower the deploy size (fewer units), undeploy "
            f"another basket, or reset the paper account first."
        )

    b.paper_account_id = acct.id
    b.status = "deployed"
    # stamp the cadence clock BEFORE committing "deployed" so a scheduler
    # tick that lands in the gap can't see a due basket and double-buy;
    # the initial rebalance below stamps it again
    b.last_rebalanced_at = datetime.now(UTC)
    db.commit()
    return _do_rebalance(db, settings, b, applied=True, reason="initial deployment")


def undeploy(db: Session, settings: Settings, basket_id: str, *, liquidate: bool = False) -> dict:
    b = _get(db, basket_id)
    acct = get_or_create_account(db)
    net, _ = _tagged_state(db, acct.id, b.id)
    sold = 0
    if liquidate:
        for sym, qty in net.items():
            if qty <= 0:
                continue
            try:
                pa_engine.place_order(
                    db, settings,
                    OrderRequest(
                        exchange=_EXCHANGE, tradingsymbol=sym, side="SELL", quantity=qty,
                        order_type="MARKET", product="CNC", tag=_tag(b.id),
                    ),
                )
                sold += 1
            except ValidationError as exc:
                logger.warning("basket_liquidate_rejected", symbol=sym, err=str(exc))
    b.status = "draft"
    b.paper_account_id = None
    db.add(
        BasketRebalanceEvent(
            basket_id=b.id, as_of=datetime.now(UTC), mode="paper",
            target_weights={}, orders=[], applied=True,
            note=f"undeployed{' + liquidated ' + str(sold) + ' positions' if liquidate else ''}",
        )
    )
    db.commit()
    return {"basket_id": str(b.id), "status": b.status, "positions_sold": sold}


def rebalance(db: Session, settings: Settings, basket_id: str, *, force: bool = False) -> dict:
    b = _get(db, basket_id)
    if b.status != "deployed":
        raise ValidationError("basket is not deployed")
    now_ist = datetime.now(IST)
    if not force and not _is_due(b, now_ist):
        return {
            "basket_id": str(b.id),
            "applied": False,
            "skipped": True,
            "reason": f"not due — next {b.rebalance_frequency} window not reached",
            "last_rebalanced_at": b.last_rebalanced_at.isoformat() if b.last_rebalanced_at else None,
        }
    return _do_rebalance(
        db, settings, b, applied=True, require_due=not force,
        reason="forced rebalance" if force else f"{b.rebalance_frequency} rebalance",
    )


def preview(db: Session, settings: Settings, basket_id: str) -> dict:
    b = _get(db, basket_id)
    return _do_rebalance(db, settings, b, applied=False, reason="preview")


def status(db: Session, settings: Settings, basket_id: str) -> dict:
    b = _get(db, basket_id)
    spec = _spec_of(b)
    acct = get_or_create_account(db)
    net, cash_flow = _tagged_state(db, acct.id, b.id)
    basket_cash = float(b.capital) + cash_flow

    hist, _ = _history(db, settings, spec) if b.status == "deployed" else ({}, [])
    refs = list(dict.fromkeys([*spec.symbols, *net.keys()]))
    prices = _prices(db, settings, refs, hist) if refs else {}

    holdings = []
    invested = 0.0
    for sym, qty in sorted(net.items()):
        px = prices.get(sym, 0.0)
        val = qty * px
        invested += val
        holdings.append({"symbol": sym, "qty": qty, "price": round(px, 2), "value": round(val, 2)})
    pv = basket_cash + invested
    for h in holdings:
        h["weight"] = round(h["value"] / pv, 4) if pv > 0 else 0.0

    now_ist = datetime.now(IST)
    recent = db.execute(
        select(BasketRebalanceEvent)
        .where(BasketRebalanceEvent.basket_id == b.id)
        .order_by(BasketRebalanceEvent.as_of.desc())
        .limit(10)
    ).scalars().all()

    return {
        "basket_id": str(b.id),
        "name": b.name,
        "status": b.status,
        "frequency": b.rebalance_frequency,
        "capital": float(b.capital),
        "portfolio_value": round(pv, 2),
        "basket_cash": round(basket_cash, 2),
        "invested_value": round(invested, 2),
        "return_pct": round((pv / float(b.capital) - 1.0) * 100.0, 2) if b.capital else None,
        "holdings": holdings,
        "last_rebalanced_at": b.last_rebalanced_at.isoformat() if b.last_rebalanced_at else None,
        "rebalance_due": b.status == "deployed" and _is_due(b, now_ist),
        "events": [
            {
                "as_of": e.as_of.isoformat(), "mode": e.mode, "applied": e.applied,
                "n_orders": len(e.orders or []), "note": e.note,
            }
            for e in recent
        ],
    }


def events(db: Session, basket_id: str, *, limit: int = 50) -> list[dict]:
    b = _get(db, basket_id)
    rows = db.execute(
        select(BasketRebalanceEvent)
        .where(BasketRebalanceEvent.basket_id == b.id)
        .order_by(BasketRebalanceEvent.as_of.desc())
        .limit(max(1, min(limit, 200)))
    ).scalars().all()
    return [
        {
            "id": str(e.id), "as_of": e.as_of.isoformat(), "mode": e.mode,
            "applied": e.applied, "target_weights": e.target_weights,
            "orders": e.orders, "note": e.note,
        }
        for e in rows
    ]


def tick_all(db: Session, settings: Settings) -> int:
    """Rebalance every deployed basket whose cadence is due. Called from the
    paper-account scheduler while the market is open. Never raises."""
    now_ist = datetime.now(IST)
    done = 0
    deployed = db.execute(
        select(Basket).where(Basket.status == "deployed")
    ).scalars().all()
    for b in deployed:
        if not _is_due(b, now_ist):
            continue
        try:
            res = _do_rebalance(
                db, settings, b, applied=True, require_due=True,
                reason=f"{b.rebalance_frequency} auto-rebalance",
            )
            if not res.get("skipped"):
                done += 1
        except Exception:  # noqa: BLE001 - one bad basket must not stall the loop
            logger.exception("basket_auto_rebalance_error", basket=str(b.id))
            db.rollback()
    return done

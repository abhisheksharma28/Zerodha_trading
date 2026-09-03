"""Deploy a library strategy to trade *inside* the paper account.

The strategy is evaluated exactly as elsewhere on the platform (the same
``TemplateStrategy`` framework, the same bar plumbing), but its order
intents are routed through ``paper_account.engine`` instead of a broker /
the deployment OMS. Fills land in the one PaperAccount portfolio; every
order it places is tagged ``strat:<run_id>`` for per-strategy P&L.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.timeframes import kite_interval
from app.backtesting.timeframes import resolve as resolve_tf
from app.config import Settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.paper_account import (
    PaperHolding,
    PaperOrder,
    PaperPosition,
    PaperStrategyRun,
)
from app.paper_account import engine, pricing
from app.paper_account.engine import OrderRequest, get_or_create_account
from app.services import broker_service
from app.strategies.base import Bar, StrategyContext
from app.strategies.library import TEMPLATES
from app.strategies.library import get_template as get_by_slug

logger = get_logger(__name__)

# in-process strategy instances, keyed by run id (rebuilt on first tick)
_RUNTIMES: dict[str, tuple[Any, StrategyContext]] = {}

_LOOKBACK_BARS = {"day": 400, "60minute": 500, "15minute": 400, "5minute": 400, "minute": 400}
_LOOKBACK_DAYS = {"day": 550, "60minute": 60, "15minute": 20, "5minute": 8, "minute": 4}


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------

def templates() -> list[dict[str, Any]]:
    out = []
    for cls in TEMPLATES:
        md = getattr(cls, "METADATA", None)
        out.append({
            "slug": cls.SLUG,
            "name": cls.NAME,
            "category": cls.CATEGORY,
            "min_instruments": cls.MIN_INSTRUMENTS,
            "max_instruments": cls.MAX_INSTRUMENTS,
            "supported_timeframes": list(cls.SUPPORTED_TIMEFRAMES),
            "params": cls.parameter_schema(),
            "presets": cls.presets(),
            "time_horizon": getattr(md, "time_horizon", None),
            "description": getattr(md, "description", None),
            "warning": getattr(md, "warning", None),
        })
    return out


# --------------------------------------------------------------------------
# run lifecycle
# --------------------------------------------------------------------------

def create_run(
    db: Session, *, slug: str, name: str, instruments: list[str], timeframe: str,
    product: str, params: dict[str, Any] | None, flatten_on_stop: bool = True,
) -> PaperStrategyRun:
    try:
        cls = get_by_slug(slug)
    except KeyError as exc:
        raise ValidationError(f"Unknown strategy '{slug}'") from exc
    refs = [r.strip().upper() for r in instruments if r.strip()]
    if not refs:
        raise ValidationError("Pick at least one instrument.")
    n = len(refs)
    if n < cls.MIN_INSTRUMENTS or (cls.MAX_INSTRUMENTS is not None and n > cls.MAX_INSTRUMENTS):
        raise ValidationError(
            f"{cls.NAME} needs {cls.MIN_INSTRUMENTS}"
            + (f"-{cls.MAX_INSTRUMENTS}" if cls.MAX_INSTRUMENTS else "+")
            + f" instruments, got {n}."
        )
    tf = resolve_tf(timeframe).token
    if cls.SUPPORTED_TIMEFRAMES and tf not in cls.SUPPORTED_TIMEFRAMES:
        raise ValidationError(f"{cls.NAME} does not support the {tf} timeframe.")
    try:
        merged = cls.resolve_params(params or {})  # validates + coerces
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Bad parameters: {exc}") from exc
    prod = product.upper()
    if prod not in ("CNC", "MIS", "NRML"):
        raise ValidationError("product must be CNC, MIS or NRML")

    acct = get_or_create_account(db)
    run = PaperStrategyRun(
        account_id=acct.id, slug=slug, name=name or cls.NAME, params=merged,
        instruments=refs, timeframe=tf, product=prod, status="ACTIVE",
        flatten_on_stop=flatten_on_stop, started_at=datetime.now(UTC), last_bar_ts={},
    )
    db.add(run)
    db.commit()
    logger.info("paper_strategy_created", slug=slug, instruments=refs, tf=tf)
    return run


def set_status(db: Session, settings: Settings, run_id: str, status: str) -> PaperStrategyRun:
    run = db.get(PaperStrategyRun, run_id)
    if run is None:
        raise ValidationError("strategy run not found")
    status = status.upper()
    if status not in ("ACTIVE", "PAUSED", "STOPPED"):
        raise ValidationError("status must be ACTIVE, PAUSED or STOPPED")
    run.status = status
    if status == "STOPPED":
        run.stopped_at = datetime.now(UTC)
        _RUNTIMES.pop(str(run.id), None)
        if run.flatten_on_stop:
            _flatten(db, settings, run)
    db.commit()
    return run


def delete_run(db: Session, run_id: str) -> None:
    run = db.get(PaperStrategyRun, run_id)
    if run is None:
        return
    _RUNTIMES.pop(str(run.id), None)
    db.delete(run)
    db.commit()


def _flatten(db: Session, settings: Settings, run: PaperStrategyRun) -> None:
    """Square off whatever this run is net long/short, from its tagged fills."""
    net = _tagged_net_qty(db, run)
    for ref, qty in net.items():
        if qty == 0:
            continue
        ex, sym = ref.split(":", 1)
        try:
            engine.place_order(db, settings, OrderRequest(
                exchange=ex, tradingsymbol=sym, side="SELL" if qty > 0 else "BUY",
                quantity=abs(qty), order_type="MARKET", product=run.product,
                tag=f"strat:{run.id}",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.info("paper_strategy_flatten_failed", ref=ref, error=str(exc))


def _tagged_net_qty(db: Session, run: PaperStrategyRun) -> dict[str, int]:
    """Net qty this run is responsible for, from its tagged completed orders."""
    rows = db.execute(
        select(PaperOrder.exchange, PaperOrder.tradingsymbol, PaperOrder.side, PaperOrder.filled_qty)
        .where(PaperOrder.account_id == run.account_id, PaperOrder.tag == f"strat:{run.id}",
               PaperOrder.status == "COMPLETE")
    ).all()
    net: dict[str, int] = {}
    for ex, sym, side, qty in rows:
        ref = f"{ex}:{sym}"
        net[ref] = net.get(ref, 0) + (qty if side == "BUY" else -qty)
    return net


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

def _client(db: Session, settings: Settings):  # noqa: ANN202
    try:
        return broker_service.build_authenticated_client(db, settings)
    except Exception:  # noqa: BLE001
        return None


def _bars_for(client: Any, token: str, kite_int: str, symbol: str) -> list[Bar]:
    days = _LOOKBACK_DAYS.get(kite_int, 400)
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days)
    try:
        rows = client.get_historical_candles(str(token), kite_int, from_dt, to_dt)
    except Exception as exc:  # noqa: BLE001
        logger.info("paper_strategy_candles_failed", symbol=symbol, error=str(exc))
        return []
    cap = _LOOKBACK_BARS.get(kite_int, 400)
    out: list[Bar] = []
    for r in rows[-cap:]:
        if len(r) < 5:
            continue
        out.append(Bar(
            timestamp=str(r[0]), open=float(r[1]), high=float(r[2]), low=float(r[3]),
            close=float(r[4]), volume=float(r[5]) if len(r) > 5 and r[5] is not None else 0.0,
            instrument=symbol,
        ))
    return out


def _current_net(db: Session, run: PaperStrategyRun, symbol: str) -> int:
    pos = db.execute(
        select(PaperPosition.net_qty).where(
            PaperPosition.account_id == run.account_id, PaperPosition.tradingsymbol == symbol,
            PaperPosition.status == "OPEN",
        )
    ).scalars().all()
    hold = db.execute(
        select(PaperHolding.qty).where(
            PaperHolding.account_id == run.account_id, PaperHolding.tradingsymbol == symbol,
        )
    ).scalars().all()
    return sum(int(x) for x in pos) + sum(int(x) for x in hold)


def tick_run(db: Session, settings: Settings, run: PaperStrategyRun) -> int:
    if run.status != "ACTIVE":
        return 0
    client = _client(db, settings)
    if client is None:
        return 0
    key = str(run.id)
    rt = _RUNTIMES.get(key)
    warming = rt is None
    if rt is None:
        cls = get_by_slug(run.slug)
        ctx = StrategyContext(parameters=dict(run.params or {}))
        strat = cls(ctx)
        strat.on_start()
        rt = (strat, ctx)
        _RUNTIMES[key] = rt
    strat, ctx = rt

    kite_int = kite_interval(run.timeframe)
    tok = {}
    for ref in run.instruments:
        ex, sym = ref.split(":", 1)
        info = pricing.resolve(db, ex, sym)
        if info and info.instrument_token:
            tok[ref] = (info.instrument_token, sym)

    last_seen: dict[str, str] = dict(run.last_bar_ts or {})
    placed = 0
    for ref, (token, sym) in tok.items():
        bars = _bars_for(client, token, kite_int, sym)
        if not bars:
            continue
        seen = last_seen.get(sym)
        new = [b for b in bars if seen is None or str(b.timestamp) > seen]
        if warming:
            # replay everything up to the last bar to warm the buffers,
            # act only on the final (most recent closed) bar
            for b in new[:-1]:
                ctx.positions = {}
                strat.on_bar(b)
                ctx.drain_pending_orders()
            new = new[-1:]
        row_ex = ref.split(":", 1)[0]
        for b in new:
            ctx.positions = {s: _current_net(db, run, s) for _r, (_t, s) in tok.items()}
            strat.on_bar(b)
            for intent in ctx.drain_pending_orders():
                run.signals += 1
                try:
                    o = engine.place_order(db, settings, OrderRequest(
                        exchange=(intent.exchange or row_ex),
                        tradingsymbol=intent.tradingsymbol,
                        side=str(intent.transaction_type).upper(),
                        quantity=int(intent.quantity),
                        order_type=str(intent.order_type or "MARKET").upper(),
                        product=run.product,
                        price=float(intent.price) if intent.price else None,
                        tag=f"strat:{run.id}",
                    ))
                    run.orders_placed += 1
                    if o.status == "COMPLETE":
                        placed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.info("paper_strategy_order_failed", run=key, error=str(exc))
            last_seen[sym] = str(b.timestamp)

    run.last_bar_ts = last_seen
    run.last_tick_at = datetime.now(UTC)
    run.error = None
    db.commit()
    return placed


def tick_all(db: Session, settings: Settings) -> int:
    acct = get_or_create_account(db)
    runs = list(db.execute(
        select(PaperStrategyRun).where(
            PaperStrategyRun.account_id == acct.id, PaperStrategyRun.status == "ACTIVE"
        )
    ).scalars().all())
    total = 0
    for run in runs:
        try:
            total += tick_run(db, settings, run)
        except Exception as exc:  # noqa: BLE001
            logger.exception("paper_strategy_tick_error", run=str(run.id))
            run.error = str(exc)[:500]
            db.rollback()
            db.add(run)
            db.commit()
    return total

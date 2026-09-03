"""Auto-trade bridge between the Trading Ideas engine and the paper account.

When the algo toggle is ON, every fresh ``LIVE`` recommendation that clears
the configured rules (minimum grade, allowed trade types, % per trade,
max open, daily-loss stop, cut-off time) is taken as a paper trade tagged
``algo:<rec_id>``. Equity entries get a protective SL-M child order; option
ideas are placed as the overlay's defined-risk spread. When the source
idea later flips to ``EXPIRED`` the matching paper exposure is squared off.

Nothing here is advice. It mechanically mirrors the screener's own output
into a demo account so the user can watch the rules play out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.market_scanner import ScanRecommendation
from app.models.paper_account import PaperAlgoConfig, PaperOrder, PaperTrade
from app.paper_account import engine, service
from app.paper_account.engine import OrderRequest, get_or_create_account

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_GRADE_RANK = {"A": 3, "B": 2, "C": 1}
_MAX_OPTION_LOTS = 5


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def get_config(db: Session) -> PaperAlgoConfig:
    acct = get_or_create_account(db)
    cfg = db.execute(
        select(PaperAlgoConfig).where(PaperAlgoConfig.account_id == acct.id).limit(1)
    ).scalar_one_or_none()
    if cfg is None:
        cfg = PaperAlgoConfig(account_id=acct.id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


_EDITABLE = {
    "enabled": bool,
    "min_grade": str,
    "pct_per_trade": float,
    "max_open_auto": int,
    "daily_loss_stop_pct": float,
    "cutoff_ist": str,
    "allow_delivery": bool,
    "allow_intraday": bool,
    "allow_options": bool,
    "equity_product": str,
}


def set_config(db: Session, patch: dict[str, Any]) -> PaperAlgoConfig:
    cfg = get_config(db)
    for key, caster in _EDITABLE.items():
        if key not in patch or patch[key] is None:
            continue
        val = caster(patch[key])
        if key == "min_grade":
            val = str(val).upper()
            if val not in _GRADE_RANK:
                raise ValidationError("min_grade must be A, B or C")
        if key == "equity_product":
            val = str(val).upper()
            if val not in ("CNC", "MIS"):
                raise ValidationError("equity_product must be CNC or MIS")
        if key == "cutoff_ist" and _parse_cutoff(str(val)) is None:
            raise ValidationError("cutoff_ist must be HH:MM")
        if key == "pct_per_trade" and not 0.1 <= float(val) <= 25.0:
            raise ValidationError("pct_per_trade must be between 0.1 and 25")
        if key == "max_open_auto" and not 1 <= int(val) <= 50:
            raise ValidationError("max_open_auto must be between 1 and 50")
        if key == "daily_loss_stop_pct" and not 0.5 <= float(val) <= 100.0:
            raise ValidationError("daily_loss_stop_pct must be between 0.5 and 100")
        setattr(cfg, key, val)
    # a fresh enable clears a stale halt from an earlier day
    if patch.get("enabled") and cfg.halted_day != _today(datetime.now(IST)):
        cfg.halted_reason = None
        cfg.halted_day = None
    db.commit()
    db.refresh(cfg)
    return cfg


def config_dict(cfg: PaperAlgoConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "min_grade": cfg.min_grade,
        "pct_per_trade": float(cfg.pct_per_trade),
        "max_open_auto": cfg.max_open_auto,
        "daily_loss_stop_pct": float(cfg.daily_loss_stop_pct),
        "cutoff_ist": cfg.cutoff_ist,
        "allow_delivery": cfg.allow_delivery,
        "allow_intraday": cfg.allow_intraday,
        "allow_options": cfg.allow_options,
        "equity_product": cfg.equity_product,
        "halted_reason": cfg.halted_reason,
        "halted_day": cfg.halted_day,
    }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _today(now: datetime) -> str:
    return now.date().isoformat()


def _parse_cutoff(hhmm: str) -> dtime | None:
    try:
        h, m = hhmm.split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def _grade_ok(rec: ScanRecommendation, min_grade: str) -> bool:
    g = (rec.score_detail or {}).get("grade") or _grade_from_conf(float(rec.confidence or 0))
    return _GRADE_RANK.get(str(g).upper(), 0) >= _GRADE_RANK.get(min_grade.upper(), 99)


def _grade_from_conf(conf: float) -> str:
    return "A" if conf >= 74 else "B" if conf >= 58 else "C"


def _style_allowed(rec: ScanRecommendation, cfg: PaperAlgoConfig) -> bool:
    return {
        "EQUITY_DELIVERY": cfg.allow_delivery,
        "EQUITY_INTRADAY": cfg.allow_intraday,
        "OPTION": cfg.allow_options,
    }.get(rec.trade_style, False)


def _already_acted(db: Session, acct_id: Any, rec_id: Any) -> bool:
    return db.execute(
        select(func.count()).select_from(PaperOrder).where(
            PaperOrder.account_id == acct_id,
            PaperOrder.tag.like(f"algo:{rec_id}%"),
        )
    ).scalar_one() > 0


def _open_algo_rec_ids(db: Session, acct_id: Any) -> set[str]:
    """rec ids that still carry net paper exposure from an algo entry."""
    rows = db.execute(
        select(PaperOrder.tag, PaperOrder.side, PaperOrder.filled_qty).where(
            PaperOrder.account_id == acct_id,
            PaperOrder.status == "COMPLETE",
            PaperOrder.tag.like("algo:%"),
        )
    ).all()
    net: dict[str, int] = {}
    for tag, side, qty in rows:
        rec_id = str(tag).split(":", 2)[1]
        net[rec_id] = net.get(rec_id, 0) + (int(qty) if side == "BUY" else -int(qty))
    return {rid for rid, q in net.items() if q != 0}


def _algo_exposure(db: Session, acct_id: Any, rec_id: str) -> dict[tuple[str, str, str], int]:
    """{(exchange, tradingsymbol, product) -> net qty} for one idea."""
    rows = db.execute(
        select(PaperOrder.exchange, PaperOrder.tradingsymbol, PaperOrder.product,
               PaperOrder.side, PaperOrder.filled_qty).where(
            PaperOrder.account_id == acct_id,
            PaperOrder.status == "COMPLETE",
            PaperOrder.tag.like(f"algo:{rec_id}%"),
        )
    ).all()
    net: dict[tuple[str, str, str], int] = {}
    for ex, sym, prod, side, qty in rows:
        key = (ex, sym, prod)
        net[key] = net.get(key, 0) + (int(qty) if side == "BUY" else -int(qty))
    return {k: v for k, v in net.items() if v != 0}


def _today_algo_realized(db: Session, acct_id: Any, day_start_utc: datetime) -> float:
    val = db.execute(
        select(func.coalesce(func.sum(PaperTrade.realized_pnl), 0.0))
        .select_from(PaperTrade)
        .join(PaperOrder, PaperOrder.id == PaperTrade.order_id)
        .where(
            PaperTrade.account_id == acct_id,
            PaperOrder.tag.like("algo:%"),
            PaperTrade.traded_at >= day_start_utc,
        )
    ).scalar_one()
    return float(val or 0.0)


# --------------------------------------------------------------------------
# take new trades
# --------------------------------------------------------------------------

def run_once(db: Session, settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    today = _today(now)
    cfg = get_config(db)
    acct = get_or_create_account(db)

    if not cfg.enabled:
        return {"enabled": False, "taken": [], "skipped": "algo trading is off"}
    if cfg.halted_day == today and cfg.halted_reason:
        return {"enabled": True, "taken": [], "skipped": f"halted: {cfg.halted_reason}"}

    cutoff = _parse_cutoff(cfg.cutoff_ist) or dtime(14, 45)
    past_cutoff = now.time() >= cutoff

    # daily-loss stop on algo-tagged activity
    day_start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    realized = _today_algo_realized(db, acct.id, day_start_utc)
    summ = service.summary(db, settings)
    net_worth = float(summ.get("net_worth") or 0.0) or float(acct.opening_balance)
    if realized <= -(float(cfg.daily_loss_stop_pct) / 100.0) * net_worth:
        cfg.halted_day = today
        cfg.halted_reason = f"daily loss stop hit (algo P&L Rs {realized:,.0f})"
        db.commit()
        logger.info("paper_algo_halted", reason=cfg.halted_reason)
        return {"enabled": True, "taken": [], "skipped": cfg.halted_reason}

    open_ids = _open_algo_rec_ids(db, acct.id)
    room = int(cfg.max_open_auto) - len(open_ids)
    if room <= 0:
        return {"enabled": True, "taken": [], "skipped": "max open auto positions reached"}
    if past_cutoff:
        return {"enabled": True, "taken": [], "skipped": "past the new-trade cut-off time"}

    recs = list(db.execute(
        select(ScanRecommendation).where(
            ScanRecommendation.status == "LIVE",
            ScanRecommendation.trading_day == today,
        ).order_by(ScanRecommendation.confidence.desc())
    ).scalars().all())

    alloc = net_worth * float(cfg.pct_per_trade) / 100.0
    taken: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_pairs: set[str] = set()

    for rec in recs:
        if room <= 0:
            break
        if not _style_allowed(rec, cfg) or not _grade_ok(rec, cfg.min_grade):
            continue
        if _already_acted(db, acct.id, rec.id):
            continue
        # one idea per pair (equity + its option express the same view)
        pair_key = str(rec.pair_id) if rec.pair_id else f"solo:{rec.id}"
        if pair_key in seen_pairs:
            continue

        try:
            if rec.trade_style == "OPTION":
                res = _take_option(db, settings, rec, alloc)
            else:
                res = _take_equity(db, settings, rec, alloc, cfg)
        except Exception as exc:  # noqa: BLE001 - one bad idea must not stop the rest
            logger.info("paper_algo_take_failed", rec=str(rec.id), error=str(exc))
            db.rollback()
            skipped.append({"rec_id": str(rec.id), "symbol": rec.tradingsymbol, "reason": str(exc)})
            continue

        if res.get("ok"):
            taken.append(res)
            seen_pairs.add(pair_key)
            room -= 1
        else:
            skipped.append({"rec_id": str(rec.id), "symbol": rec.tradingsymbol,
                            "reason": res.get("reason", "not taken")})

    if taken:
        db.commit()
    return {"enabled": True, "taken": taken, "skipped": skipped, "room_left": max(room, 0)}


def _take_equity(
    db: Session, settings: Settings, rec: ScanRecommendation, alloc: float, cfg: PaperAlgoConfig,
) -> dict[str, Any]:
    entry = float(rec.entry)
    if entry <= 0:
        return {"ok": False, "reason": "no entry price"}
    qty = int(alloc // entry)
    if qty < 1:
        return {"ok": False, "reason": f"allocation Rs {alloc:,.0f} < 1 share @ {entry:,.0f}"}

    long = rec.direction == "LONG"
    # a short can't sit in a delivery (CNC) account, so those go MIS
    product = cfg.equity_product if (rec.trade_style == "EQUITY_DELIVERY" and long) else "MIS"

    order = engine.place_order(db, settings, OrderRequest(
        exchange=rec.exchange, tradingsymbol=rec.tradingsymbol,
        side="BUY" if long else "SELL", quantity=qty,
        order_type="MARKET", product=product, tag=f"algo:{rec.id}",
    ))
    if order.status != "COMPLETE":
        return {"ok": False, "reason": order.status_message or order.status}

    fill = float(order.avg_fill_price or entry)
    sl = float(rec.stop_loss)
    sl_placed = False
    sl_ok = (sl < fill) if long else (sl > fill)
    if sl_ok:
        try:
            engine.place_order(db, settings, OrderRequest(
                exchange=rec.exchange, tradingsymbol=rec.tradingsymbol,
                side="SELL" if long else "BUY", quantity=qty,
                order_type="SL-M", product=product, trigger_price=round(sl, 2),
                tag=f"algo:{rec.id}:sl",
            ))
            sl_placed = True
        except Exception as exc:  # noqa: BLE001 - entry still stands without the child SL
            logger.info("paper_algo_sl_failed", rec=str(rec.id), error=str(exc))

    return {
        "ok": True, "rec_id": str(rec.id), "symbol": rec.tradingsymbol,
        "trade_style": rec.trade_style, "direction": rec.direction,
        "qty": qty, "product": product, "fill": round(fill, 2),
        "stop_child": sl_placed, "grade": (rec.score_detail or {}).get("grade"),
    }


def _take_option(
    db: Session, settings: Settings, rec: ScanRecommendation, alloc: float,
) -> dict[str, Any]:
    ov = rec.option_overlay or {}
    legs = ov.get("legs") or []
    lot = int(ov.get("lot_size") or 0)
    net_debit = float(ov.get("net_debit") or 0.0)
    if len(legs) != 2 or lot <= 0 or net_debit <= 0:
        return {"ok": False, "reason": "no usable option overlay"}

    per_lot_cost = net_debit * lot
    lots = int(alloc // per_lot_cost)
    lots = max(1, min(lots, _MAX_OPTION_LOTS))
    qty = lots * lot

    placed = []
    for leg in legs:
        sym = leg.get("tradingsymbol")
        side = str(leg.get("side") or "BUY").upper()
        if not sym:
            return {"ok": False, "reason": "option leg missing a tradingsymbol"}
        order = engine.place_order(db, settings, OrderRequest(
            exchange="NFO", tradingsymbol=sym, side=side, quantity=qty,
            order_type="MARKET", product="NRML", tag=f"algo:{rec.id}",
        ))
        if order.status != "COMPLETE":
            db.rollback()
            return {"ok": False, "reason": f"{side} {sym}: {order.status_message or order.status}"}
        placed.append({"side": side, "symbol": sym, "fill": float(order.avg_fill_price or 0.0)})

    return {
        "ok": True, "rec_id": str(rec.id), "symbol": rec.tradingsymbol,
        "trade_style": "OPTION", "structure": ov.get("structure"),
        "lots": lots, "qty": qty, "legs": placed,
        "grade": (rec.score_detail or {}).get("grade"),
    }


# --------------------------------------------------------------------------
# manage open auto positions
# --------------------------------------------------------------------------

def manage(db: Session, settings: Settings) -> dict[str, Any]:
    """Square off auto positions whose source idea has expired, and clean up
    their resting child SL orders."""
    acct = get_or_create_account(db)
    closed: list[dict[str, Any]] = []
    for rec_id in _open_algo_rec_ids(db, acct.id):
        rec = db.get(ScanRecommendation, rec_id)
        if rec is None or rec.status != "EXPIRED":
            continue
        exposure = _algo_exposure(db, acct.id, rec_id)
        for (ex, sym, product), qty in exposure.items():
            try:
                engine.place_order(db, settings, OrderRequest(
                    exchange=ex, tradingsymbol=sym,
                    side="SELL" if qty > 0 else "BUY", quantity=abs(qty),
                    order_type="MARKET", product=product, tag=f"algo:{rec_id}:exit",
                ))
                closed.append({"rec_id": rec_id, "symbol": sym, "qty": -qty,
                               "outcome": rec.outcome})
            except Exception as exc:  # noqa: BLE001
                logger.info("paper_algo_exit_failed", rec=rec_id, sym=sym, error=str(exc))
        # drop any still-resting SL child
        for o in db.execute(
            select(PaperOrder).where(
                PaperOrder.account_id == acct.id, PaperOrder.status == "OPEN",
                PaperOrder.tag == f"algo:{rec_id}:sl",
            )
        ).scalars().all():
            o.status = "CANCELLED"
            o.status_message = "source idea expired"
    if closed:
        db.commit()
    return {"closed": closed}


# --------------------------------------------------------------------------
# API view
# --------------------------------------------------------------------------

def status(db: Session, settings: Settings) -> dict[str, Any]:
    cfg = get_config(db)
    acct = get_or_create_account(db)
    open_ids = _open_algo_rec_ids(db, acct.id)
    now = datetime.now(IST)
    day_start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return {
        "config": config_dict(cfg),
        "open_auto_positions": len(open_ids),
        "max_open_auto": cfg.max_open_auto,
        "today_realized_pnl": round(_today_algo_realized(db, acct.id, day_start_utc), 2),
        "halted": bool(cfg.halted_day == _today(now) and cfg.halted_reason),
    }

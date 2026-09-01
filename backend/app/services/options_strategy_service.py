"""Lifecycle for scheduled options-basket strategy instances.

One instance = one intended entry for one monthly expiry. The three legs are
recorded as normal Order rows tagged with the instance's ``basket_id``; the
OptionsStrategyInstance row holds the basket economics and the CREATED →
… → CLOSED lifecycle so target / stop / short-strike monitoring and restart
recovery have a single source of truth.

Paper mode is fully implemented (fills simulated at executable prices +
slippage). Live basket execution is deliberately **not** auto-enabled — it
must go through the existing execution guard and a JSON-capable broker
client for basket margin; ``enter`` refuses live until that is wired.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.backtesting.costs import CostConfig, CostModel
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import (
    AuditAction,
    ChangeEntityType,
    OptionsStrategyStatus,
    OrderStatus,
    OrderType,
    ProductType,
    TradingMode,
)
from app.models.enums import OrderTransactionType as TxnType
from app.models.options_strategy import OptionsStrategyInstance
from app.models.order import Order
from app.options.expiry import select_monthly_expiry
from app.strategies.options.base import MarketData
from app.strategies.options.hni_monthly import (
    METADATA,
    PRESETS,
    SLUG,
    HniConfig,
    basket_pnl,
    evaluate_entry,
    evaluate_exit,
    parameter_schema,
)

logger = get_logger(__name__)

_TERMINAL = {
    OptionsStrategyStatus.TARGET_HIT, OptionsStrategyStatus.STOP_LOSS,
    OptionsStrategyStatus.SHORT_STRIKE_EXIT, OptionsStrategyStatus.TIME_EXIT,
    OptionsStrategyStatus.EXPIRY_EXIT, OptionsStrategyStatus.MANUAL_EXIT,
    OptionsStrategyStatus.FAILED, OptionsStrategyStatus.CLOSED,
}
_EXIT_STATUS = {
    "TARGET": OptionsStrategyStatus.TARGET_HIT,
    "STOP_LOSS": OptionsStrategyStatus.STOP_LOSS,
    "SHORT_STRIKE_EXIT": OptionsStrategyStatus.SHORT_STRIKE_EXIT,
    "TIME_EXIT": OptionsStrategyStatus.TIME_EXIT,
    "EXPIRY_EXIT": OptionsStrategyStatus.EXPIRY_EXIT,
}
_COST_MODEL = CostModel(CostConfig())


def template_info() -> dict[str, Any]:
    return {**METADATA, "parameters": parameter_schema(), "presets": PRESETS}


def _resolve_config(preset: str | None, overrides: dict[str, Any] | None) -> HniConfig:
    data: dict[str, Any] = {}
    if preset:
        if preset not in PRESETS:
            raise ValidationError(f"Unknown preset '{preset}' ({sorted(PRESETS)}).")
        data.update(PRESETS[preset])
    if overrides:
        data.update(overrides)
    try:
        return HniConfig.from_dict(data)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Invalid config: {exc}") from exc


def create_instance(
    db: Session,
    *,
    mode: TradingMode,
    preset: str | None = "as_specified",
    overrides: dict[str, Any] | None = None,
    as_of: date | None = None,
    strategy_version_id: Any = None,
) -> OptionsStrategyInstance:
    """Create a WAITING instance for the next qualifying monthly expiry.

    Idempotent: at most one non-terminal instance per (slug, mode, expiry).
    """
    if mode == TradingMode.LIVE:
        raise ValidationError(
            "Live basket execution is not enabled for this strategy yet — create it in "
            "'paper' or 'simulation' mode."
        )
    cfg = _resolve_config(preset, overrides)
    today = as_of or datetime.now().date()

    # find the nearest future monthly expiry to key the basket_id on
    sel = select_monthly_expiry(cfg.underlying, today, min_dte=1, max_dte=400,
                                require_friday=False)
    expiry = sel.expiry
    basket_id = f"{SLUG}:{mode.value}:{expiry.isoformat()}"

    existing = db.execute(
        select(OptionsStrategyInstance).where(OptionsStrategyInstance.basket_id == basket_id)
    ).scalar_one_or_none()
    if existing is not None and existing.status not in _TERMINAL:
        raise ConflictError(
            f"A non-terminal instance for {expiry.isoformat()} ({mode.value}) already exists "
            f"({existing.id})."
        )
    if existing is not None:
        basket_id = f"{basket_id}:{int(datetime.now(UTC).timestamp())}"

    inst = OptionsStrategyInstance(
        slug=SLUG, mode=mode, status=OptionsStrategyStatus.CREATED,
        config=cfg.to_dict(), basket_id=basket_id, underlying=cfg.underlying, expiry=expiry,
        strategy_version_id=strategy_version_id,
    )
    db.add(inst)
    db.flush()
    record_audit(
        db, action=AuditAction.CREATE, entity_type=ChangeEntityType.DEPLOYMENT,
        entity_id=inst.id, mode=mode,
        summary=f"Created options strategy '{METADATA['name']}' for expiry {expiry.isoformat()} "
                f"({mode.value})",
        after={"basket_id": basket_id},
    )
    db.commit()
    db.refresh(inst)
    return inst


def evaluate(
    db: Session, instance_id: Any, md: MarketData, *, as_of: datetime | None = None
) -> dict[str, Any]:
    inst = _get(db, instance_id)
    cfg = HniConfig.from_dict(inst.config)
    when = as_of or _entry_datetime(cfg, datetime.now())
    dec = evaluate_entry(cfg, when, md)
    inst.not_eligible_reason = None if dec.eligible else dec.reason
    inst.status = (
        OptionsStrategyStatus.ENTRY_PENDING if dec.eligible else inst.status
    )
    db.commit()
    return {
        "eligible": dec.eligible, "reason": dec.reason, "as_of": when.isoformat(),
        "spot": dec.spot, "expiry": dec.expiry.isoformat() if dec.expiry else None,
        "dte": dec.dte,
        "basket": dec.basket.to_dict() if dec.basket else None,
        "diagnostics": dec.diagnostics,
    }


def enter(
    db: Session, instance_id: Any, md: MarketData, *, as_of: datetime | None = None
) -> OptionsStrategyInstance:
    """Paper/simulation entry: evaluate, then simulate leg fills at
    executable prices + slippage and persist the basket + Order rows."""
    inst = _get(db, instance_id)
    if inst.status not in (OptionsStrategyStatus.CREATED, OptionsStrategyStatus.VALIDATING,
                           OptionsStrategyStatus.ENTRY_PENDING):
        raise ConflictError(f"Instance is {inst.status.value}, cannot enter.")
    if inst.mode == TradingMode.LIVE:
        raise ValidationError("Live basket execution is not enabled.")

    cfg = HniConfig.from_dict(inst.config)
    when = as_of or _entry_datetime(cfg, datetime.now())
    inst.status = OptionsStrategyStatus.VALIDATING
    db.flush()

    dec = evaluate_entry(cfg, when, md)
    if not dec.eligible or dec.basket is None:
        inst.status = OptionsStrategyStatus.CREATED
        inst.not_eligible_reason = dec.reason
        db.commit()
        return inst

    basket = dec.basket
    for leg in basket.legs:
        q = md.option_quote(cfg.underlying, leg.expiry, leg.strike, "CE", when)
        if q is None:
            inst.status = OptionsStrategyStatus.FAILED
            inst.not_eligible_reason = f"Lost quote for leg {leg.label} at execution."
            db.commit()
            return inst
        raw = q.ask if leg.action == "BUY" else q.bid
        leg.entry_price = round(
            _COST_MODEL.fill_price_with_slippage(leg.action, raw, segment="options"), 2
        )
        order = Order(
            mode=inst.mode, options_instance_id=inst.id,
            tradingsymbol=leg.tradingsymbol, exchange="NFO",
            transaction_type=TxnType(leg.action), order_type=OrderType.MARKET,
            product=ProductType.NRML, quantity=leg.quantity, price=leg.entry_price,
            status=OrderStatus.COMPLETE, placed_at=datetime.now(UTC),
            raw_request={"basket_id": inst.basket_id, "leg": leg.label, "strike": leg.strike,
                         "expiry": leg.expiry.isoformat(), "option_type": "CE",
                         "theoretical_strike": leg.theoretical_strike,
                         "strike_difference": leg.strike_difference},
        )
        db.add(order)
        db.flush()
        leg_dict = leg.to_dict()
        leg_dict["order_id"] = str(order.id)

    inst.status = OptionsStrategyStatus.ACTIVE
    inst.entry_date = when.date()
    inst.entry_time = when
    inst.dte_at_entry = dec.dte
    inst.spot_at_entry = basket.spot_at_entry
    inst.lot_size = basket.lot_size
    inst.strike_a, inst.strike_b, inst.strike_c = (leg.strike for leg in basket.legs)
    inst.basket = basket.to_dict()
    inst.net_credit = basket.net_credit
    inst.credit_pct = basket.credit_pct
    inst.deployed_capital = basket.deployed_capital
    inst.deployed_capital_source = basket.deployed_capital_source
    inst.target_amount = basket.target_amount
    inst.stop_loss_amount = basket.stop_loss_amount
    inst.last_spot = basket.spot_at_entry
    inst.last_pnl = 0.0
    inst.last_evaluated_at = datetime.now(UTC)

    record_audit(
        db, action=AuditAction.ORDER_PLACED, entity_type=ChangeEntityType.DEPLOYMENT,
        entity_id=inst.id, mode=inst.mode,
        summary=(
            f"HNI basket ENTERED: {basket.underlying} {basket.expiry.isoformat()} "
            f"A{inst.strike_a:.0f}/B{inst.strike_b:.0f}/C{inst.strike_c:.0f}, "
            f"credit {basket.credit_pct:.2f}%, deployed ₹{basket.deployed_capital:,.0f} "
            f"({basket.deployed_capital_source})"
        ),
        after={"basket_id": inst.basket_id},
        actor="options-worker",
    )
    db.commit()
    db.refresh(inst)
    return inst


def monitor(
    db: Session, instance_id: Any, md: MarketData, *, now: datetime | None = None
) -> OptionsStrategyInstance:
    inst = _get(db, instance_id)
    if inst.status != OptionsStrategyStatus.ACTIVE or not inst.basket:
        return inst
    cfg = HniConfig.from_dict(inst.config)
    now = now or datetime.now()
    basket = _basket_from_row(inst)

    spot = md.spot(cfg.underlying, now)
    leg_prices: dict[str, float] = {}
    for leg in basket.legs:
        q = md.option_quote(cfg.underlying, leg.expiry, leg.strike, "CE", now)
        if q is not None:
            leg_prices[leg.label] = q.mid
    if spot is None or len(leg_prices) < len(basket.legs):
        logger.warning("hni_monitor_stale_data", instance_id=str(instance_id))
        return inst

    prev_spot = float(inst.last_spot) if inst.last_spot is not None else None
    dec = evaluate_exit(cfg, basket, now=now, entry_time=inst.entry_time or now,
                        spot=spot, prev_spot=prev_spot, leg_prices=leg_prices)
    inst.last_spot = spot
    inst.last_pnl = round(dec.pnl, 2)
    inst.last_evaluated_at = datetime.now(UTC)

    if not dec.should_exit:
        db.commit()
        return inst

    _close_basket(db, inst, md, now, _EXIT_STATUS[dec.reason], dec.reason,
                  detail=f"{dec.detail} ({dec.pnl_pct:.2f}% of deployed)")
    db.commit()
    db.refresh(inst)
    return inst


def _close_basket(
    db: Session, inst: OptionsStrategyInstance, md: MarketData, now: datetime,
    status: OptionsStrategyStatus, reason: str, *, detail: str = "",
) -> None:
    cfg = HniConfig.from_dict(inst.config)
    basket = _basket_from_row(inst)
    exit_prices: dict[str, float] = {}
    for leg in basket.legs:
        q = md.option_quote(cfg.underlying, leg.expiry, leg.strike, "CE", now)
        close_side = "SELL" if leg.action == "BUY" else "BUY"
        raw = (q.bid if close_side == "SELL" else q.ask) if q else leg.entry_price
        px = round(_COST_MODEL.fill_price_with_slippage(close_side, raw, segment="options"), 2)
        exit_prices[leg.label] = px
        db.add(Order(
            mode=inst.mode, options_instance_id=inst.id,
            tradingsymbol=leg.tradingsymbol, exchange="NFO",
            transaction_type=TxnType(close_side), order_type=OrderType.MARKET,
            product=ProductType.NRML, quantity=leg.quantity, price=px,
            status=OrderStatus.COMPLETE, placed_at=datetime.now(UTC),
            raw_request={"basket_id": inst.basket_id, "leg": leg.label, "closing": True},
        ))
    gross = sum(
        leg.signed_dir * (exit_prices[leg.label] - leg.entry_price) * leg.quantity
        for leg in basket.legs
    )
    fees = sum(
        _COST_MODEL.charge(
            "SELL" if leg.action == "BUY" else "BUY", exit_prices[leg.label], leg.quantity,
            "options", reference_price=exit_prices[leg.label],
        ).total
        for leg in basket.legs
    )
    inst.status = status
    inst.exit_reason = reason
    inst.exit_time = datetime.now(UTC)
    inst.exit_prices = exit_prices
    inst.realized_pnl = round(gross, 2)
    inst.fees = round(fees, 2)
    inst.net_pnl = round(gross - fees, 2)
    record_audit(
        db, action=AuditAction.UPDATE, entity_type=ChangeEntityType.DEPLOYMENT,
        entity_id=inst.id, mode=inst.mode,
        summary=f"HNI basket EXIT ({reason}): net ₹{inst.net_pnl:,.0f} — {detail}".strip(),
        actor="options-worker",
    )


def manual_exit(db: Session, instance_id: Any, md: MarketData) -> OptionsStrategyInstance:
    inst = _get(db, instance_id)
    if inst.status != OptionsStrategyStatus.ACTIVE:
        raise ConflictError(f"Instance is {inst.status.value}, not ACTIVE.")
    _close_basket(db, inst, md, datetime.now(), OptionsStrategyStatus.MANUAL_EXIT,
                  "MANUAL_EXIT", detail="operator manual exit")
    db.commit()
    db.refresh(inst)
    return inst


def recover_live_instances(db: Session, kite_client: Any) -> list[str]:
    """On restart: reconcile every non-terminal LIVE instance against broker
    positions instead of re-entering. Returns basket_ids reconciled. LIVE
    entry is not enabled yet, so in practice this only guards against a
    future misfire — it never opens a position."""
    reconciled: list[str] = []
    rows = db.execute(
        select(OptionsStrategyInstance).where(
            OptionsStrategyInstance.mode == TradingMode.LIVE,
            OptionsStrategyInstance.status.notin_(list(_TERMINAL)),
        )
    ).scalars().all()
    if not rows:
        return reconciled
    try:
        positions = kite_client.get_positions().get("net", [])
    except Exception:  # noqa: BLE001
        logger.warning("hni_recovery_no_positions")
        return reconciled
    held = {p["tradingsymbol"]: p for p in positions if p.get("quantity")}
    for inst in rows:
        want = {leg["tradingsymbol"] for leg in (inst.basket or {}).get("legs", [])}
        if want and want.issubset(held):
            inst.status = OptionsStrategyStatus.ACTIVE
            reconciled.append(inst.basket_id)
        else:
            inst.status = OptionsStrategyStatus.FAILED
            inst.not_eligible_reason = (
                "Restart recovery: broker positions do not match the recorded basket; "
                "marked FAILED rather than risk a duplicate."
            )
    db.commit()
    return reconciled


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _get(db: Session, instance_id: Any) -> OptionsStrategyInstance:
    inst = db.get(OptionsStrategyInstance, instance_id)
    if inst is None:
        raise NotFoundError(f"Options strategy instance {instance_id} not found")
    return inst


def _entry_datetime(cfg: HniConfig, now: datetime) -> datetime:
    hh, mm = cfg.entry_time
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _basket_from_row(inst: OptionsStrategyInstance):
    from app.strategies.options.base import BasketSpec, OptionLeg

    raw = inst.basket or {}
    legs = [
        OptionLeg(
            label=lg["label"], action=lg["action"], option_type="CE", strike=float(lg["strike"]),
            expiry=date.fromisoformat(lg["expiry"]), lots=int(lg["lots"]),
            lot_size=int(lg["lot_size"]), tradingsymbol=lg["tradingsymbol"],
            instrument_token=lg["instrument_token"],
            theoretical_strike=float(lg.get("theoretical_strike", 0.0)),
            strike_difference=float(lg.get("strike_difference", 0.0)),
            entry_price=float(lg.get("entry_price", 0.0)),
        )
        for lg in raw.get("legs", [])
    ]
    return BasketSpec(
        underlying=raw["underlying"], expiry=date.fromisoformat(raw["expiry"]),
        spot_at_entry=float(raw["spot_at_entry"]), lot_size=int(raw["lot_size"]), legs=legs,
        net_credit=float(raw["net_credit"]), credit_pct=float(raw["credit_pct"]),
        deployed_capital=float(raw["deployed_capital"]),
        deployed_capital_source=raw["deployed_capital_source"],
        target_amount=float(raw["target_amount"]), stop_loss_amount=float(raw["stop_loss_amount"]),
        short_strike=float(raw["short_strike"]),
    )


def basket_current_pnl(inst: OptionsStrategyInstance, leg_prices: dict[str, float]) -> float:
    return basket_pnl(_basket_from_row(inst), leg_prices)


def list_instances(db: Session) -> list[OptionsStrategyInstance]:
    return list(
        db.execute(
            select(OptionsStrategyInstance).order_by(OptionsStrategyInstance.created_at.desc())
        ).scalars().all()
    )

"""Live-engine monitoring: latency percentiles + engine health.

Feeds the compact "● LIVE  ⚡ x.x ms" indicator and the latency dashboard.
Numbers come from real instrumentation in the strategy-evaluation worker
(see app.live.latency); this endpoint only reads a published snapshot, it
never synthesizes values.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.brokers.base import OrderRequest
from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import BrokerNotConnectedError, ValidationError
from app.core.logging import get_logger
from app.live import engine as live_engine
from app.live import telemetry
from app.live.circuit_breakers import BREAKERS, is_market_open
from app.live.oms import OMS_ENGINE
from app.live.risk import RISK
from app.services import broker_service

logger = get_logger(__name__)
router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/latency")
def latency() -> dict:
    """Latest engine snapshot. Shape:

        {
          available, source ("redis" | "in_process"), stale, age_seconds,
          updated_epoch,
          latency: { stages: {market_data: {...}, ...}, headline: {...} },
          engine: { running_deployments, poll_interval_seconds, ... },
          thresholds_ms: { excellent, fast, moderate, high }
        }

    ``thresholds_ms`` are advisory bands for colouring the widget; the
    frontend decides presentation. They are configurable via env.
    """
    s = get_settings()
    snap = telemetry.read()
    snap["thresholds_ms"] = {
        "excellent": s.latency_threshold_excellent_ms,
        "fast": s.latency_threshold_fast_ms,
        "moderate": s.latency_threshold_moderate_ms,
        "high": s.latency_threshold_high_ms,
    }
    # The Kite ticker runs in THIS (API) process, so its status is read
    # directly rather than via the cross-process telemetry snapshot.
    snap.setdefault("engine", {})
    snap["engine"]["ticker"] = live_engine.engine_status()
    return snap


@router.get("/market-state")
def market_state() -> dict:
    """Current in-memory market snapshot (last price / OHLC / age per
    instrument). Read straight from RAM — no broker call, no DB."""
    from app.live.market_state import MARKET_STATE

    return MARKET_STATE.snapshot()


@router.get("/risk")
def risk_snapshot() -> dict:
    """In-memory pre-trade risk state: per-deployment order counts, open
    positions, realized P&L and kill-switch status."""
    return RISK.snapshot()


class KillSwitchBody(BaseModel):
    scope: str = "all"           # "all" or a deployment id
    engaged: bool = True         # True = stop new orders; False = resume


@router.post("/risk/kill-switch")
def kill_switch(body: KillSwitchBody) -> dict:
    """Engage / release the kill switch. Engaging is always safe — it only
    stops NEW orders reaching an executor or the broker; open positions are
    untouched. Releasing resumes normal risk checks."""
    if body.scope == "all":
        (RISK.kill_all if body.engaged else RISK.resume_all)()
    else:
        (RISK.kill if body.engaged else RISK.resume)(body.scope)
    logger.warning(
        "risk_kill_switch", scope=body.scope, engaged=body.engaged, source="api"
    )
    return RISK.snapshot(None if body.scope == "all" else body.scope)


@router.get("/oms")
def oms() -> dict:
    """Order Management System snapshot: per-state counts and the recent
    order lifecycle (create → submit → ack → fill timestamps + latencies)."""
    return OMS_ENGINE.snapshot()


@router.get("/circuit-breakers")
def circuit_breakers() -> dict:
    """Automatic trading-halt state (stale market data, dropped feed).
    Independent of the manual kill switch."""
    snap = BREAKERS.snapshot()
    snap["market_open"] = is_market_open()
    return snap


@router.post("/circuit-breakers/override")
def circuit_breaker_override() -> dict:
    """Operator override: resume trading even though a breaker condition may
    still be present. Use with care."""
    BREAKERS.force_clear_all()
    logger.warning("circuit_breaker_override_via_api")
    return BREAKERS.snapshot()


class FlattenBody(BaseModel):
    confirm: str = ""


@router.post("/flatten")
def emergency_flatten(
    body: FlattenBody,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """EMERGENCY: close every open LIVE broker position with market orders
    and engage the global kill switch so strategies can't re-open. Requires
    ``confirm == "FLATTEN ALL"``."""
    if body.confirm != "FLATTEN ALL":
        raise ValidationError('Send {"confirm": "FLATTEN ALL"} to run the emergency flatten.')

    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        raise ValidationError(str(exc)) from exc

    RISK.kill_all()  # stop new strategy orders first

    net = client.get_positions().get("net", [])
    placed: list[dict] = []
    for p in net:
        qty = int(p.get("quantity") or 0)
        if qty == 0:
            continue
        sym = p["tradingsymbol"]
        side = "SELL" if qty > 0 else "BUY"
        req = OrderRequest(
            tradingsymbol=sym,
            exchange=p.get("exchange", "NSE"),
            transaction_type=side,
            order_type="MARKET",
            quantity=abs(qty),
            product=p.get("product", "MIS"),
        )
        try:
            result = client.place_order(req)
            internal_id = f"flatten:{sym}:{result.broker_order_id}"
            OMS_ENGINE.register(
                internal_id, deployment_id="__flatten__", tradingsymbol=sym,
                exchange=req.exchange, side=side, quantity=abs(qty),
            )
            OMS_ENGINE.mark_submitted(internal_id, result.broker_order_id)
            placed.append({"tradingsymbol": sym, "side": side, "quantity": abs(qty),
                           "broker_order_id": result.broker_order_id})
        except Exception as exc:  # noqa: BLE001 - report per-leg, keep flattening the rest
            logger.exception("flatten_leg_failed", tradingsymbol=sym)
            placed.append({"tradingsymbol": sym, "side": side, "quantity": abs(qty),
                           "error": str(exc)})

    logger.warning("emergency_flatten_executed", legs=len(placed))
    return {"kill_switch": "engaged", "positions_flattened": placed}


@router.get("/indicators")
def indicators() -> dict:
    """Live incremental indicators (EMA/SMA/RSI/ATR/VWAP/Bollinger/MACD/…),
    stepped one bar at a time off the tick stream — never recomputed from
    history. Keyed by tradingsymbol."""
    from app.live.indicator_engine import INDICATOR_ENGINE
    from app.live.market_stream import HUB

    by_symbol: dict[str, dict] = {}
    for token, snap in INDICATOR_ENGINE.snapshot_all().items():
        sym = HUB.symbol_for(token) or str(token)
        by_symbol[sym] = snap
    return {
        "interval_seconds": INDICATOR_ENGINE.interval,
        "instruments": by_symbol,
    }

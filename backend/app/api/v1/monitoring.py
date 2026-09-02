"""Live-engine monitoring: latency percentiles + engine health.

Feeds the compact "● LIVE  ⚡ x.x ms" indicator and the latency dashboard.
Numbers come from real instrumentation in the strategy-evaluation worker
(see app.live.latency); this endpoint only reads a published snapshot, it
never synthesizes values.
"""

from fastapi import APIRouter

from app.config import get_settings
from app.live import engine as live_engine
from app.live import telemetry

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

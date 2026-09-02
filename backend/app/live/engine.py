"""Owns the single Kite market-data ticker for the API process and bridges
it to the frontend fan-out hub.

Two ways the ticker starts:

* eagerly from the FastAPI lifespan when ``LIVE_TICKER_ENABLED=true`` (with
  the configured watchlist), and
* lazily via :func:`ensure_started` the first time a browser opens a live
  chart — a chart subscription is itself explicit intent, so it does not
  require the env flag, only a connected Zerodha session.

Ticks flow: KiteTicker -> MARKET_STATE (RAM) + HUB.publish -> browser WS.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.config import Settings, get_settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.live.indicator_engine import INDICATOR_ENGINE
from app.live.market_state import MARKET_STATE
from app.live.market_stream import HUB
from app.market_data.instruments import resolve_instrument_token
from app.market_data.kite_ticker import KiteTicker
from app.market_data.nse_universe import NIFTY_50
from app.services import broker_service

logger = get_logger(__name__)

_ticker: KiteTicker | None = None
_task: asyncio.Task[None] | None = None
_monitor_task: asyncio.Task[None] | None = None
_state: str = "stopped"  # stopped | no_broker | error | running
_detail: str = ""
_start_lock = asyncio.Lock()


def _watchlist(settings: Settings) -> list[str]:
    raw = (settings.live_ticker_instruments or "").strip()
    syms = (
        [s.strip() for s in raw.split(",") if s.strip()]
        if raw
        else [f"NSE:{sym}" for sym, _n, _s in NIFTY_50]
    )
    return syms[: settings.live_ticker_max_instruments]


def resolve_symbols(symbols: list[str]) -> tuple[list[tuple[int, str, str]], list[str]]:
    """[(token, input_symbol, tradingsymbol), ...], [unknown_inputs]."""
    triples: list[tuple[int, str, str]] = []
    unknown: list[str] = []
    for sym in symbols:
        try:
            token, tradingsymbol = resolve_instrument_token(sym)
            triples.append((int(token), sym, tradingsymbol))
        except Exception:  # noqa: BLE001
            unknown.append(sym)
    return triples, unknown


async def _create_ticker(settings: Settings, tokens: list[int]) -> bool:
    """Build + launch the ticker task. Returns True on success."""
    global _ticker, _task, _state, _detail
    db = SessionLocal()
    try:
        client = broker_service.build_authenticated_client(db, settings)
        api_key = settings.zerodha_api_key
        access_token = client.access_token
    except BrokerNotConnectedError as exc:
        _state, _detail = "no_broker", str(exc)
        return False
    except Exception as exc:  # noqa: BLE001
        _state, _detail = "error", f"{type(exc).__name__}: {exc}"
        logger.warning("live_ticker_start_failed", error=_detail)
        return False
    finally:
        db.close()

    if not api_key or not access_token:
        _state, _detail = "no_broker", "broker session has no access token"
        return False

    def _fan_out(tick: dict[str, Any]) -> None:
        HUB.publish(tick)
        INDICATOR_ENGINE.on_tick(tick)

    _ticker = KiteTicker(
        api_key,
        access_token,
        tokens,
        mode=settings.live_ticker_mode,
        market_state=MARKET_STATE,
        on_tick=_fan_out,
    )
    _task = asyncio.create_task(_ticker.run(), name="kite-ticker")
    global _monitor_task
    _monitor_task = asyncio.create_task(_monitor_loop(), name="live-monitor")
    _state = "running"
    _detail = f"mode={settings.live_ticker_mode}"
    logger.info("live_ticker_started", instruments=len(tokens), mode=settings.live_ticker_mode)
    return True


async def _monitor_loop() -> None:
    """Every ~2s: feed the circuit breakers a market-data health reading, and
    on a broker-feed reconnect kick a best-effort order + position resync."""
    from app.live.circuit_breakers import BREAKERS, is_market_open

    prev_connected: bool | None = None
    stale_halt = get_settings().circuit_breaker_stale_halt_seconds
    while _ticker is not None:
        try:
            connected = _ticker.connected
            BREAKERS.observe(
                feed_connected=connected,
                seconds_since_tick=MARKET_STATE.seconds_since_any_tick(),
                stale_threshold=stale_halt,
                market_open=is_market_open(),
            )
            if prev_connected is False and connected:
                logger.info("live_feed_reconnected_resyncing")
                _resync_after_reconnect()
            prev_connected = connected
        except Exception:  # noqa: BLE001
            logger.exception("live_monitor_loop_error")
        await asyncio.sleep(2.0)


def _resync_after_reconnect() -> None:
    """Reconcile OMS orders + refresh the risk engine's position book from
    the broker, on its own thread (sync DB + broker calls)."""

    def _run() -> None:
        from app.live.oms import OMS_ENGINE
        from app.live.reconciler import reconcile
        from app.live.risk import RISK

        db = SessionLocal()
        try:
            client = broker_service.build_authenticated_client(db, get_settings())
            reconcile(db, client)
            db.commit()
            try:
                positions = client.get_positions().get("net", [])
                for dep_id in {o.deployment_id for o in OMS_ENGINE.open_orders()}:
                    book = {
                        p["tradingsymbol"]: int(p["quantity"])
                        for p in positions
                        if int(p.get("quantity") or 0) != 0
                    }
                    RISK.sync_positions(dep_id, book)
            except Exception as exc:  # noqa: BLE001
                logger.warning("live_reconnect_position_sync_failed", error=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("live_reconnect_resync_failed")
        finally:
            db.close()

    threading.Thread(target=_run, name="live-resync", daemon=True).start()


async def start(settings: Settings | None = None) -> None:
    """Eager startup from the lifespan. Only runs the ticker up-front when
    LIVE_TICKER_ENABLED is set; otherwise it waits for a chart subscription."""
    settings = settings or get_settings()
    if not settings.live_ticker_enabled:
        _set_stopped("LIVE_TICKER_ENABLED not set — ticker starts on first chart subscription")
        return
    async with _start_lock:
        if _ticker is not None:
            return
        triples, _unknown = resolve_symbols(_watchlist(settings))
        await _create_ticker(settings, [t for t, _in, _ts in triples])


async def ensure_started() -> str:
    """Start the ticker on demand (a browser opened a live chart). Idempotent."""
    global _ticker
    if _ticker is not None and _state == "running":
        return _state
    async with _start_lock:
        if _ticker is not None and _state == "running":
            return _state
        await _create_ticker(get_settings(), [])
    return _state


async def ensure_upstream(tokens: list[int]) -> None:
    if _ticker is not None and tokens:
        await _ticker.subscribe(tokens)


async def drop_upstream(tokens: list[int]) -> None:
    if _ticker is not None and tokens:
        await _ticker.unsubscribe(tokens)


async def stop() -> None:
    global _ticker, _task, _monitor_task
    if _ticker is not None:
        _ticker.request_stop()
    if _monitor_task is not None:
        _monitor_task.cancel()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _task.cancel()
        except Exception:  # noqa: BLE001
            logger.exception("live_ticker_stop_error")
    _ticker, _task, _monitor_task = None, None, None
    _set_stopped("stopped")


def _set_stopped(detail: str) -> None:
    global _state, _detail
    _state, _detail = "stopped", detail


def engine_status() -> dict[str, Any]:
    st: dict[str, Any] = {"state": _state, "detail": _detail, "hub": HUB.status()}
    if _ticker is not None:
        st["ticker"] = _ticker.status()
    stale_after = get_settings().live_ticker_stale_seconds
    since = MARKET_STATE.seconds_since_any_tick()
    st["market_state"] = {
        "instrument_count": MARKET_STATE.snapshot()["instrument_count"],
        "seconds_since_any_tick": round(since, 3) if since is not None else None,
        "stale": since is not None and since > stale_after,
    }
    from app.live.circuit_breakers import BREAKERS

    st["circuit_breakers"] = BREAKERS.snapshot()
    return st

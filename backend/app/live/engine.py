"""Supervises the live market-data ticker for the API process.

Started from the FastAPI lifespan. Off by default — set ``LIVE_TICKER_ENABLED
=true`` to run it. When enabled it needs a connected Zerodha session; if
there is none at startup the ticker simply doesn't start and
:func:`engine_status` says so (a later slice adds live re-arming).

The ticker folds ticks into :data:`app.live.market_state.MARKET_STATE`; this
module only owns the task lifecycle and the instrument selection.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import Settings, get_settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.live.market_state import MARKET_STATE
from app.market_data.instruments import resolve_instrument_token
from app.market_data.kite_ticker import KiteTicker
from app.market_data.nse_universe import NIFTY_50
from app.services import broker_service

logger = get_logger(__name__)

_ticker: KiteTicker | None = None
_task: asyncio.Task[None] | None = None
_state: str = "disabled"  # disabled | no_broker | no_instruments | running | error
_detail: str = ""


def _watchlist(settings: Settings) -> list[str]:
    raw = (settings.live_ticker_instruments or "").strip()
    if raw:
        syms = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        syms = [f"NSE:{sym}" for sym, _n, _s in NIFTY_50]
    return syms[: settings.live_ticker_max_instruments]


def _resolve_tokens(symbols: list[str]) -> list[int]:
    tokens: list[int] = []
    for sym in symbols:
        try:
            token, _ts = resolve_instrument_token(sym)
            tokens.append(int(token))
        except Exception as exc:  # noqa: BLE001 - skip unknowns, keep the rest
            logger.info("live_ticker_unresolved_symbol", symbol=sym, error=str(exc))
    return tokens


async def start(settings: Settings | None = None) -> None:
    global _ticker, _task, _state, _detail
    settings = settings or get_settings()

    if not settings.live_ticker_enabled:
        _state, _detail = "disabled", "LIVE_TICKER_ENABLED is not set"
        return

    db = SessionLocal()
    try:
        client = broker_service.build_authenticated_client(db, settings)
        api_key = settings.zerodha_api_key
        access_token = client.access_token
    except BrokerNotConnectedError as exc:
        _state, _detail = "no_broker", str(exc)
        logger.info("live_ticker_not_started_no_broker")
        return
    except Exception as exc:  # noqa: BLE001
        _state, _detail = "error", f"{type(exc).__name__}: {exc}"
        logger.warning("live_ticker_start_failed", error=_detail)
        return
    finally:
        db.close()

    if not access_token or not api_key:
        _state, _detail = "no_broker", "broker session has no access token"
        return

    tokens = _resolve_tokens(_watchlist(settings))
    if not tokens:
        _state, _detail = "no_instruments", "no instrument tokens resolved for the watchlist"
        return

    _ticker = KiteTicker(
        api_key,
        access_token,
        tokens,
        mode=settings.live_ticker_mode,
        market_state=MARKET_STATE,
    )
    _task = asyncio.create_task(_ticker.run(), name="kite-ticker")
    _state, _detail = "running", f"{len(tokens)} instruments, mode={settings.live_ticker_mode}"
    logger.info("live_ticker_started", instruments=len(tokens), mode=settings.live_ticker_mode)


async def stop() -> None:
    global _ticker, _task, _state
    if _ticker is not None:
        _ticker.request_stop()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _task.cancel()
        except Exception:  # noqa: BLE001
            logger.exception("live_ticker_stop_error")
    _ticker, _task = None, None
    if _state == "running":
        _state = "disabled"


def engine_status() -> dict[str, Any]:
    st: dict[str, Any] = {"state": _state, "detail": _detail}
    if _ticker is not None:
        st["ticker"] = _ticker.status()
    stale_after = get_settings().live_ticker_stale_seconds
    since = MARKET_STATE.seconds_since_any_tick()
    st["market_state"] = {
        "instrument_count": MARKET_STATE.snapshot()["instrument_count"],
        "seconds_since_any_tick": round(since, 3) if since is not None else None,
        "stale": since is not None and since > stale_after,
    }
    return st

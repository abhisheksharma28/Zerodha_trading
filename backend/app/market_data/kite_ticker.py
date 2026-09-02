"""Async Zerodha Kite ticker client.

Owns a single WebSocket connection to ``wss://ws.kite.trade``, parses the
binary frames (see app.market_data.kite_tick_parser) and folds every tick
into the in-memory :data:`app.live.market_state.MARKET_STATE`. Each frame is
wrapped in a ``LATENCY.span("market_data")`` so T0->T2 (tick received ->
market state updated) is measured for real.

Subscriptions are dynamic: :meth:`subscribe` / :meth:`unsubscribe` can be
called at any time (e.g. when a browser opens a chart) and take effect
immediately if the socket is up, or on the next (re)connect otherwise.
An optional ``on_tick`` callback lets a fan-out hub forward ticks to
frontend WebSocket clients.

Reconnects on drop with exponential backoff. Never raises out of
:meth:`run` — a ticker failure must not take the process down.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import ssl
import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlencode

import certifi
import websockets

from app.core.logging import get_logger
from app.live.latency import LATENCY, STAGE_MARKET_DATA
from app.live.market_state import MARKET_STATE, MarketState
from app.market_data.kite_tick_parser import parse_binary_message

logger = get_logger(__name__)

_WS_URL = "wss://ws.kite.trade"
_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0
_MODE_LTP = "ltp"
_MODE_QUOTE = "quote"
_MODE_FULL = "full"
_VALID_MODES = {_MODE_LTP, _MODE_QUOTE, _MODE_FULL}
# Explicit CA bundle — the stdlib ssl default context can't always find the
# system roots (notably on macOS Python builds); certifi ships with httpx.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

TickCallback = Callable[[dict[str, Any]], None]


class KiteTicker:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        instrument_tokens: Iterable[int] = (),
        *,
        mode: str = _MODE_QUOTE,
        market_state: MarketState | None = None,
        on_tick: TickCallback | None = None,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")
        self._api_key = api_key
        self._access_token = access_token
        self._tokens: set[int] = {int(t) for t in instrument_tokens}
        self._mode = mode
        self._state = market_state or MARKET_STATE
        self._on_tick = on_tick

        self._stop = asyncio.Event()
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self.connected = False
        self.ticks_total = 0
        self.frames_total = 0
        self.last_tick_monotonic = 0.0
        self.last_error: str | None = None
        self._recent_frame_times: deque[float] = deque(maxlen=200)

    # --- public API ---------------------------------------------------

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def subscribed_tokens(self) -> set[int]:
        return set(self._tokens)

    async def subscribe(self, tokens: Iterable[int]) -> None:
        new = {int(t) for t in tokens} - self._tokens
        self._tokens |= {int(t) for t in tokens}
        if new and self._ws is not None and self.connected:
            await self._send({"a": "subscribe", "v": sorted(new)})
            await self._send({"a": "mode", "v": [self._mode, sorted(new)]})

    async def unsubscribe(self, tokens: Iterable[int]) -> None:
        drop = {int(t) for t in tokens} & self._tokens
        self._tokens -= drop
        if drop and self._ws is not None and self.connected:
            await self._send({"a": "unsubscribe", "v": sorted(drop)})

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        window = [t for t in self._recent_frame_times if now - t <= 5.0]
        tps = len(window) / 5.0 if window else 0.0
        return {
            "connected": self.connected,
            "subscribed": len(self._tokens),
            "mode": self._mode,
            "ticks_total": self.ticks_total,
            "frames_total": self.frames_total,
            "frames_per_sec": round(tps, 2),
            "last_tick_age_seconds": round(now - self.last_tick_monotonic, 3)
            if self.last_tick_monotonic
            else None,
            "last_error": self.last_error,
        }

    async def run(self) -> None:
        backoff = _BACKOFF_START
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = _BACKOFF_START  # clean close -> reset backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect, never propagate
                self.connected = False
                self._ws = None
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("kite_ticker_disconnected", error=self.last_error, retry_in=backoff)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                backoff = min(_BACKOFF_MAX, backoff * 2)
        self.connected = False
        self._ws = None
        logger.info("kite_ticker_stopped")

    # --- internals --------------------------------------------------

    def _url(self) -> str:
        return f"{_WS_URL}?" + urlencode(
            {"api_key": self._api_key, "access_token": self._access_token}
        )

    async def _send(self, obj: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            return
        async with self._send_lock:
            await ws.send(json.dumps(obj))

    async def _session(self) -> None:
        async with websockets.connect(
            self._url(),
            ssl=_SSL_CONTEXT,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**22,
        ) as ws:
            self._ws = ws
            self.connected = True
            self.last_error = None
            logger.info("kite_ticker_connected", instruments=len(self._tokens), mode=self._mode)
            if self._tokens:
                await self._send({"a": "subscribe", "v": sorted(self._tokens)})
                await self._send({"a": "mode", "v": [self._mode, sorted(self._tokens)]})

            try:
                while not self._stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except TimeoutError:
                        continue  # no ticks (market closed) — keep the socket open
                    if isinstance(raw, bytes):
                        self._on_binary(raw)
                    else:
                        self._on_text(raw)
            finally:
                self.connected = False
                self._ws = None

    def _on_binary(self, raw: bytes) -> None:
        if len(raw) < 2:
            return  # heartbeat
        with LATENCY.span(STAGE_MARKET_DATA):
            ticks = parse_binary_message(raw)
            for tick in ticks:
                self._state.apply_tick(tick)
        now = time.monotonic()
        self.frames_total += 1
        self.ticks_total += len(ticks)
        self.last_tick_monotonic = now
        self._recent_frame_times.append(now)
        if self._on_tick is not None:
            for tick in ticks:
                try:
                    self._on_tick(tick)
                except Exception:  # noqa: BLE001 - a bad consumer must not kill the ticker
                    logger.exception("kite_ticker_on_tick_failed")

    def _on_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("type") == "error":
            self.last_error = str(msg.get("data"))
            logger.warning("kite_ticker_server_error", detail=self.last_error)

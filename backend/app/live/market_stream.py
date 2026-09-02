"""Fan-out of live ticks to frontend WebSocket clients.

The Kite ticker (one connection to the broker, in this process) calls
:meth:`MarketStreamHub.publish` for every tick. The hub forwards each tick
to the browser connections that subscribed to that instrument, via a
bounded per-client queue (newest-wins on overflow, so one slow tab can't
back-pressure the ticker or other tabs).

Reference counting per instrument token tells :mod:`app.live.engine` when to
``subscribe`` / ``unsubscribe`` on the upstream Kite socket.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_QUEUE_MAX = 256


@dataclass(eq=False)
class ClientConn:
    id: int
    tokens: set[int] = field(default_factory=set)
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX)
    )
    dropped: int = 0


class MarketStreamHub:
    def __init__(self) -> None:
        self._clients: set[ClientConn] = set()
        self._refcount: dict[int, int] = {}
        self._symbol_by_token: dict[int, str] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()

    # --- client lifecycle ------------------------------------------

    async def add_client(self) -> ClientConn:
        async with self._lock:
            conn = ClientConn(id=self._next_id)
            self._next_id += 1
            self._clients.add(conn)
            return conn

    async def remove_client(self, conn: ClientConn) -> list[int]:
        """Detach the client. Returns tokens whose refcount hit zero."""
        async with self._lock:
            self._clients.discard(conn)
            freed: list[int] = []
            for tok in list(conn.tokens):
                self._refcount[tok] = self._refcount.get(tok, 1) - 1
                if self._refcount[tok] <= 0:
                    self._refcount.pop(tok, None)
                    freed.append(tok)
            conn.tokens.clear()
            return freed

    async def subscribe(self, conn: ClientConn, pairs: list[tuple[int, str]]) -> list[int]:
        """Add (token, tradingsymbol) subscriptions for one client. Returns
        tokens that are newly needed upstream (refcount 0 -> 1)."""
        async with self._lock:
            newly_needed: list[int] = []
            for tok, sym in pairs:
                self._symbol_by_token[tok] = sym
                if tok not in conn.tokens:
                    conn.tokens.add(tok)
                    self._refcount[tok] = self._refcount.get(tok, 0) + 1
                    if self._refcount[tok] == 1:
                        newly_needed.append(tok)
            return newly_needed

    async def unsubscribe(self, conn: ClientConn, tokens: list[int]) -> list[int]:
        async with self._lock:
            freed: list[int] = []
            for tok in tokens:
                if tok in conn.tokens:
                    conn.tokens.discard(tok)
                    self._refcount[tok] = self._refcount.get(tok, 1) - 1
                    if self._refcount[tok] <= 0:
                        self._refcount.pop(tok, None)
                        freed.append(tok)
            return freed

    # --- hot path (sync, called from the ticker) ------------------

    def publish(self, tick: dict[str, Any]) -> None:
        token = tick.get("instrument_token")
        if token is None or not self._clients:
            return
        token = int(token)
        payload = {
            "type": "tick",
            "token": token,
            "symbol": self._symbol_by_token.get(token),
            "ltp": tick.get("last_price"),
            "ohlc": tick.get("ohlc"),
            "volume": tick.get("volume_traded"),
            "oi": tick.get("oi"),
            "ts": tick.get("exchange_timestamp") or tick.get("last_trade_time"),
        }
        for conn in self._clients:
            if token not in conn.tokens:
                continue
            try:
                conn.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # newest-wins: drop the oldest, enqueue this one
                with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                    conn.queue.get_nowait()
                    conn.queue.put_nowait(payload)
                conn.dropped += 1

    def status(self) -> dict[str, Any]:
        return {
            "clients": len(self._clients),
            "instruments": len(self._refcount),
            "dropped_total": sum(c.dropped for c in self._clients),
        }


HUB = MarketStreamHub()

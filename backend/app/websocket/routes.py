"""Browser-facing market-data WebSocket: ``/ws/market``.

Protocol (JSON both ways):

    client -> {"type": "subscribe",   "symbols": ["NSE:RELIANCE", ...]}
              {"type": "unsubscribe", "symbols": [...]}
              {"type": "ping"}
    server -> {"type": "hello", "engine": {...}}
              {"type": "subscribed", "symbols": [...], "unknown": [...]}
              {"type": "tick", "token": 738561, "symbol": "RELIANCE",
                        "ltp": 1312.4, "ohlc": {...}, "volume": ..., "ts": ...}
              {"type": "pong"}

The first subscription lazily starts the Kite ticker (needs a connected
Zerodha session). Ticks are fanned out through app.live.market_stream.HUB.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.live import engine
from app.live.market_stream import HUB

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/ws/market")
async def market_ws(ws: WebSocket) -> None:
    await ws.accept()
    conn = await HUB.add_client()
    state = await engine.ensure_started()
    await ws.send_json({"type": "hello", "engine": engine.engine_status(), "ticker_state": state})

    async def reader() -> None:
        while True:
            msg = await ws.receive_json()
            action = msg.get("type")
            symbols = [s for s in (msg.get("symbols") or []) if isinstance(s, str)]
            if action == "subscribe":
                triples, unknown = engine.resolve_symbols(symbols)
                needed = await HUB.subscribe(conn, [(t, inp) for t, inp, _ts in triples])
                await engine.ensure_upstream(needed)
                await ws.send_json(
                    {
                        "type": "subscribed",
                        "symbols": [inp for _t, inp, _ts in triples],
                        "unknown": unknown,
                    }
                )
            elif action == "unsubscribe":
                triples, _unknown = engine.resolve_symbols(symbols)
                freed = await HUB.unsubscribe(conn, [t for t, _inp, _ts in triples])
                await engine.drop_upstream(freed)
            elif action == "ping":
                await ws.send_json({"type": "pong"})

    async def writer() -> None:
        while True:
            payload = await conn.queue.get()
            await ws.send_json(payload)

    tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                logger.warning("market_ws_task_error", error=f"{type(exc).__name__}: {exc}")
    finally:
        for t in tasks:
            t.cancel()
        freed = await HUB.remove_client(conn)
        await engine.drop_upstream(freed)

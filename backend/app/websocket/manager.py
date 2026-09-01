"""Backend-to-frontend WebSocket fan-out (distinct from
app.market_data.kite_ws, which is backend-to-Kite).

Placeholder connection manager: the monitoring UI (requirement #7) will
subscribe here for live deployment status, order fills, and P&L ticks. Not
yet wired into app.main — added once app.workers has something real to
publish.
"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                self.disconnect(ws)

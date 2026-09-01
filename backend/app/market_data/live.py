"""Recent-candle feed for the strategy-evaluation worker.

Distinct from app.market_data.cache (which caches wide historical ranges for
backtests): this pulls a short, always-fresh trailing window of candles for a
running deployment and is deliberately not cached — a paper/simulation
strategy must see new bars as they close.
"""

from datetime import datetime, timedelta

from app.brokers.base import BrokerClient
from app.market_data.instruments import resolve_instrument_token
from app.strategies.base import Bar


class LiveCandleFeed:
    def __init__(self, broker_client: BrokerClient) -> None:
        self._client = broker_client
        self._token_cache: dict[str, tuple[str, str]] = {}

    def _resolve(self, symbol: str) -> tuple[str, str]:
        if symbol not in self._token_cache:
            self._token_cache[symbol] = resolve_instrument_token(symbol)
        return self._token_cache[symbol]

    def recent_bars(self, symbol: str, interval: str, lookback: timedelta) -> list[Bar]:
        token, tradingsymbol = self._resolve(symbol)
        to_dt = datetime.now()
        from_dt = to_dt - lookback
        rows = self._client.get_historical_candles(token, interval, from_dt, to_dt)
        return [
            Bar(
                timestamp=row[0],
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
                instrument=tradingsymbol,
            )
            for row in rows
        ]

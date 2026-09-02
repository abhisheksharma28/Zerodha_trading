"""In-memory market state — the live decision path reads from here, never
from the database.

One :class:`InstrumentState` per subscribed instrument, updated in place by
the ticker as frames arrive. Reads are lock-free (dict lookup + attribute
read); :meth:`MarketState.snapshot` takes a short lock to copy.

``recv_monotonic`` is stamped with ``time.monotonic()`` on every update so
staleness ("no tick for N seconds") can be judged without trusting exchange
or wall-clock timestamps.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InstrumentState:
    instrument_token: int
    last_price: float = 0.0
    volume_traded: int = 0
    average_traded_price: float = 0.0
    total_buy_quantity: int = 0
    total_sell_quantity: int = 0
    ohlc: dict[str, float] = field(default_factory=dict)
    depth: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    oi: int = 0
    last_trade_time: int = 0
    exchange_timestamp: int = 0
    mode: str = ""
    recv_monotonic: float = 0.0
    updates: int = 0

    @property
    def best_bid(self) -> float | None:
        buy = self.depth.get("buy") or []
        return float(buy[0]["price"]) if buy else None

    @property
    def best_ask(self) -> float | None:
        sell = self.depth.get("sell") or []
        return float(sell[0]["price"]) if sell else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_token": self.instrument_token,
            "last_price": self.last_price,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "volume_traded": self.volume_traded,
            "ohlc": dict(self.ohlc),
            "oi": self.oi,
            "mode": self.mode,
            "age_seconds": round(max(0.0, time.monotonic() - self.recv_monotonic), 3)
            if self.recv_monotonic
            else None,
            "updates": self.updates,
        }


class MarketState:
    def __init__(self) -> None:
        self._by_token: dict[int, InstrumentState] = {}
        self._lock = threading.Lock()
        self._total_updates = 0
        self._last_update_monotonic = 0.0

    def apply_tick(self, tick: dict[str, Any]) -> InstrumentState:
        token = int(tick["instrument_token"])
        now = time.monotonic()
        st = self._by_token.get(token)
        if st is None:
            st = InstrumentState(instrument_token=token)
            self._by_token[token] = st

        if "last_price" in tick:
            st.last_price = float(tick["last_price"])
        if "volume_traded" in tick:
            st.volume_traded = int(tick["volume_traded"])
        if "average_traded_price" in tick:
            st.average_traded_price = float(tick["average_traded_price"])
        if "total_buy_quantity" in tick:
            st.total_buy_quantity = int(tick["total_buy_quantity"])
        if "total_sell_quantity" in tick:
            st.total_sell_quantity = int(tick["total_sell_quantity"])
        if tick.get("ohlc"):
            st.ohlc = dict(tick["ohlc"])
        if tick.get("depth"):
            st.depth = tick["depth"]
        if "oi" in tick:
            st.oi = int(tick["oi"])
        if "last_trade_time" in tick:
            st.last_trade_time = int(tick["last_trade_time"])
        if "exchange_timestamp" in tick:
            st.exchange_timestamp = int(tick["exchange_timestamp"])
        st.mode = str(tick.get("mode") or st.mode)
        st.recv_monotonic = now
        st.updates += 1

        self._total_updates += 1
        self._last_update_monotonic = now
        return st

    def get(self, instrument_token: int) -> InstrumentState | None:
        return self._by_token.get(int(instrument_token))

    def last_price(self, instrument_token: int) -> float | None:
        st = self._by_token.get(int(instrument_token))
        return st.last_price if st and st.last_price else None

    def age_seconds(self, instrument_token: int) -> float | None:
        st = self._by_token.get(int(instrument_token))
        if st is None or not st.recv_monotonic:
            return None
        return max(0.0, time.monotonic() - st.recv_monotonic)

    def stale_tokens(self, threshold_seconds: float) -> list[int]:
        now = time.monotonic()
        return [
            t
            for t, st in self._by_token.items()
            if st.recv_monotonic and (now - st.recv_monotonic) > threshold_seconds
        ]

    def seconds_since_any_tick(self) -> float | None:
        if not self._last_update_monotonic:
            return None
        return max(0.0, time.monotonic() - self._last_update_monotonic)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            instruments = {str(t): st.as_dict() for t, st in self._by_token.items()}
        since = self.seconds_since_any_tick()
        return {
            "instrument_count": len(instruments),
            "total_updates": self._total_updates,
            "seconds_since_any_tick": round(since, 3) if since is not None else None,
            "instruments": instruments,
        }

    def reset(self) -> None:  # test hook
        with self._lock:
            self._by_token.clear()
            self._total_updates = 0
            self._last_update_monotonic = 0.0


# Process-global. The ticker writes; strategies / endpoints read.
MARKET_STATE = MarketState()

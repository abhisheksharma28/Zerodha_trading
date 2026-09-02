"""Aggregate a live tick stream into fixed-interval OHLCV bars, per instrument.

One :class:`BarBuilder` per instrument. Feed it ``(last_price, cumulative_
day_volume, epoch_seconds)`` from each tick; it returns a completed bar dict
the moment a bucket rolls over, otherwise ``None``. Bar volume is the delta
of Kite's cumulative day volume across the bucket.

Time bucketing is ``floor(ts / interval) * interval`` — fine for the live
indicator feed at 1m/5m; session-anchored grids (30m/1h) are the strategy
engine's concern, not this.
"""

from __future__ import annotations

import time
from typing import Any


class BarBuilder:
    def __init__(self, interval_seconds: int = 60) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval = interval_seconds
        self._bucket: int | None = None
        self._o = 0.0
        self._h = 0.0
        self._l = 0.0
        self._c = 0.0
        self._vol_at_open = 0.0
        self._vol_now = 0.0

    def _start(self, bucket: int, price: float, cum_volume: float) -> None:
        self._bucket = bucket
        self._o = self._h = self._l = self._c = price
        self._vol_at_open = cum_volume
        self._vol_now = cum_volume

    def _finish(self) -> dict[str, Any]:
        return {
            "bucket": self._bucket,
            "open": self._o,
            "high": self._h,
            "low": self._l,
            "close": self._c,
            "volume": max(0.0, self._vol_now - self._vol_at_open),
        }

    def on_tick(
        self, last_price: float, cum_volume: float | None = None, epoch_seconds: float | None = None
    ) -> dict[str, Any] | None:
        ts = float(epoch_seconds) if epoch_seconds is not None else time.time()
        vol = float(cum_volume) if cum_volume is not None else self._vol_now
        bucket = int(ts // self.interval) * self.interval

        if self._bucket is None:
            self._start(bucket, last_price, vol)
            return None

        if bucket != self._bucket:
            completed = self._finish()
            self._start(bucket, last_price, vol)
            return completed

        self._h = max(self._h, last_price)
        self._l = min(self._l, last_price)
        self._c = last_price
        self._vol_now = vol
        return None

    def current(self) -> dict[str, Any] | None:
        if self._bucket is None:
            return None
        return self._finish()

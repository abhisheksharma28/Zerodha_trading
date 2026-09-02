"""Live incremental-indicator engine.

Fed straight off the Kite tick stream (see app.live.engine): each instrument
gets a :class:`BarBuilder` and an :class:`IndicatorSet`. On every tick the
bar builder advances; when a bar closes the indicator set is stepped once,
O(1) — nothing is ever recomputed from history.

Read the current values via :meth:`snapshot` / :meth:`snapshot_all` (the
``/monitoring/indicators`` endpoint). Thread-safe: the ticker writes on the
event loop, HTTP handlers read from the thread pool.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.live.bar_builder import BarBuilder
from app.live.indicators import IndicatorSet

_DEFAULT_INTERVAL = 60


class IndicatorEngine:
    def __init__(self, interval_seconds: int = _DEFAULT_INTERVAL) -> None:
        self.interval = interval_seconds
        self._builders: dict[int, BarBuilder] = {}
        self._sets: dict[int, IndicatorSet] = {}
        self._last_bar_epoch: dict[int, float] = {}
        self._lock = threading.Lock()

    def on_tick(self, tick: dict[str, Any]) -> None:
        token = tick.get("instrument_token")
        price = tick.get("last_price")
        if token is None or price is None:
            return
        token = int(token)
        vol = tick.get("volume_traded")
        ts = tick.get("exchange_timestamp") or tick.get("last_trade_time")

        with self._lock:
            builder = self._builders.get(token)
            if builder is None:
                builder = BarBuilder(self.interval)
                self._builders[token] = builder
                self._sets[token] = IndicatorSet()
            bar = builder.on_tick(float(price), vol, ts)
            if bar is not None:
                self._sets[token].update_bar(
                    high=bar["high"], low=bar["low"], close=bar["close"], volume=bar["volume"]
                )
                self._last_bar_epoch[token] = time.time()

    def snapshot(self, token: int) -> dict[str, Any] | None:
        with self._lock:
            s = self._sets.get(int(token))
            if s is None:
                return None
            snap = s.snapshot()
            snap["last_bar_age_seconds"] = (
                round(time.time() - self._last_bar_epoch[token], 1)
                if token in self._last_bar_epoch
                else None
            )
            return snap

    def snapshot_all(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            tokens = list(self._sets)
        return {t: self.snapshot(t) or {} for t in tokens}

    def reset(self) -> None:  # test hook
        with self._lock:
            self._builders.clear()
            self._sets.clear()
            self._last_bar_epoch.clear()


INDICATOR_ENGINE = IndicatorEngine()

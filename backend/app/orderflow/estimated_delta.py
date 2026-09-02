"""ESTIMATED live delta / cumulative delta.

This is the honest ceiling of what Kite's feed allows and it is labelled
ESTIMATED everywhere it surfaces.

How it works, per instrument:

* Each ``full``-mode snapshot carries the *cumulative* day volume. The
  volume that traded since the previous snapshot is
  ``max(0, volume_traded - prev_volume_traded)``.
* That slice is assigned a side by the quote rule: last price at/above the
  best ask -> BUY, at/below the best bid -> SELL, strictly inside the
  spread -> tick rule (up-tick BUY / down-tick SELL), and if price is
  unchanged the previous side is carried.
* ``bar_delta`` accumulates signed slice volume within a fixed-width time
  bucket; ``cvd`` is the running total from the session start (first
  snapshot seen today) or since the process started, whichever is later.

Known limits (returned as ``caveats``): ~1 Hz sampling merges many real
trades into one slice; there is no exchange trade-side flag; the first
snapshot each day cannot be split from the prior close, so the opening
slice is dropped; nothing here can be reconstructed after the fact.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.orderflow.types import DataTier

_MAX_BARS = 720  # e.g. 12h of 1-min buckets
_QUOTE_RULE = "QUOTE_RULE"
_TICK_RULE = "TICK_RULE"
_CARRY = "CARRY_PREV"

_CONFIDENCE = {_QUOTE_RULE: 0.7, _TICK_RULE: 0.5, _CARRY: 0.3}


@dataclass
class _Bar:
    bucket_ts: int
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    trades: int = 0

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def volume(self) -> float:
        return self.buy_volume + self.sell_volume


@dataclass
class _InstrumentFlow:
    token: int
    prev_volume: int | None = None
    prev_price: float | None = None
    last_side: int = 0  # +1 buy, -1 sell, 0 unknown
    day_key: int = 0
    cvd: float = 0.0
    bars: deque[_Bar] = field(default_factory=lambda: deque(maxlen=_MAX_BARS))
    samples: int = 0
    dropped_opening: int = 0
    method_counts: dict[str, int] = field(default_factory=dict)

    def _bar_for(self, bucket_ts: int) -> _Bar:
        if self.bars and self.bars[-1].bucket_ts == bucket_ts:
            return self.bars[-1]
        bar = _Bar(bucket_ts=bucket_ts)
        self.bars.append(bar)
        return bar


class EstimatedDeltaEngine:
    """Process-global, fed by the ticker fan-out. Thread-safe for the
    single-writer / many-reader pattern used here."""

    def __init__(self, bar_seconds: int = 60) -> None:
        self._bar_seconds = bar_seconds
        self._by_token: dict[int, _InstrumentFlow] = {}
        self._lock = threading.Lock()

    # --- hot path (called from KiteTicker fan-out) ------------------
    def on_tick(self, tick: dict[str, Any]) -> None:
        # a bad snapshot must never take down the ticker fan-out
        with contextlib.suppress(Exception):
            self._ingest(tick)

    def _ingest(self, tick: dict[str, Any]) -> None:
        token = tick.get("instrument_token")
        vol = tick.get("volume_traded")
        price = tick.get("last_price")
        if token is None or vol is None or price is None:
            return
        token = int(token)
        vol = int(vol)
        price = float(price)
        now = time.time()
        day_key = int(now // 86400)

        with self._lock:
            fl = self._by_token.get(token)
            if fl is None:
                fl = _InstrumentFlow(token=token)
                self._by_token[token] = fl

            if fl.day_key != day_key:
                fl.day_key = day_key
                fl.prev_volume = None
                fl.prev_price = None
                fl.cvd = 0.0
                fl.last_side = 0

            fl.samples += 1

            if fl.prev_volume is None:
                fl.prev_volume = vol
                fl.prev_price = price
                fl.dropped_opening += 1
                return

            slice_vol = max(0, vol - fl.prev_volume)
            fl.prev_volume = vol
            if slice_vol == 0:
                fl.prev_price = price
                return

            side, method = self._classify(tick, price, fl.prev_price, fl.last_side)
            fl.prev_price = price
            fl.last_side = side
            fl.method_counts[method] = fl.method_counts.get(method, 0) + 1

            bucket_ts = int(now // self._bar_seconds) * self._bar_seconds
            bar = fl._bar_for(bucket_ts)
            if side >= 0:
                bar.buy_volume += slice_vol
                fl.cvd += slice_vol
            else:
                bar.sell_volume += slice_vol
                fl.cvd -= slice_vol
            bar.trades += 1

    @staticmethod
    def _classify(
        tick: dict[str, Any], price: float, prev_price: float | None, last_side: int
    ) -> tuple[int, str]:
        depth = tick.get("depth") or {}
        buy = depth.get("buy") or []
        sell = depth.get("sell") or []
        best_bid = float(buy[0]["price"]) if buy and buy[0].get("price") else None
        best_ask = float(sell[0]["price"]) if sell and sell[0].get("price") else None
        if best_ask is not None and price >= best_ask:
            return 1, _QUOTE_RULE
        if best_bid is not None and price <= best_bid:
            return -1, _QUOTE_RULE
        if prev_price is not None and price != prev_price:
            return (1, _TICK_RULE) if price > prev_price else (-1, _TICK_RULE)
        return (last_side if last_side != 0 else 1), _CARRY

    # --- reads (API) ----------------------------------------------
    def snapshot(self, token: int, *, limit: int = 240) -> dict[str, Any]:
        with self._lock:
            fl = self._by_token.get(int(token))
            if fl is None or not fl.bars:
                return {
                    "tier": DataTier.ESTIMATED.value,
                    "available": False,
                    "reason": "No live snapshots ingested for this instrument yet.",
                    "bar_seconds": self._bar_seconds,
                    "caveats": self._caveats(),
                }
            bars = list(fl.bars)[-limit:]
            total_methods = sum(fl.method_counts.values()) or 1
            conf = sum(_CONFIDENCE.get(m, 0.3) * n for m, n in fl.method_counts.items()) / total_methods
            cum = fl.cvd - sum(b.delta for b in list(fl.bars)[len(fl.bars) - len(bars):])
            series = []
            for b in bars:
                cum += b.delta
                series.append({
                    "ts": b.bucket_ts,
                    "buy_volume": round(b.buy_volume, 2),
                    "sell_volume": round(b.sell_volume, 2),
                    "delta": round(b.delta, 2),
                    "volume": round(b.volume, 2),
                    "cvd": round(cum, 2),
                    "trades": b.trades,
                })
            cur = bars[-1]
            return {
                "tier": DataTier.ESTIMATED.value,
                "available": True,
                "instrument_token": fl.token,
                "bar_seconds": self._bar_seconds,
                "samples": fl.samples,
                "dropped_opening_slices": fl.dropped_opening,
                "classification_mix": dict(fl.method_counts),
                "classification_confidence": round(conf, 3),
                "session_cvd": round(fl.cvd, 2),
                "current_bar": {
                    "ts": cur.bucket_ts,
                    "buy_volume": round(cur.buy_volume, 2),
                    "sell_volume": round(cur.sell_volume, 2),
                    "delta": round(cur.delta, 2),
                    "volume": round(cur.volume, 2),
                },
                "series": series,
                "caveats": self._caveats(),
            }

    @staticmethod
    def _caveats() -> list[str]:
        return [
            "ESTIMATED - not exchange-confirmed order flow.",
            "~1 Hz snapshots merge many real trades into one signed slice.",
            "Side inferred by quote rule (last vs best bid/ask), tick-rule fallback.",
            "Opening slice each day is dropped (no prior cumulative volume).",
            "Live only - cannot be reconstructed for past sessions.",
        ]

    def reset(self) -> None:  # test hook
        with self._lock:
            self._by_token.clear()


ORDERFLOW_DELTA = EstimatedDeltaEngine()

"""Per-stage latency instrumentation for the live trading path.

Design rules (Phase 0):

* Timing uses ``time.perf_counter_ns()`` — a monotonic, high-resolution
  clock. Wall-clock timestamps are NEVER used for latency maths (NTP steps,
  DST, and clock skew make them meaningless for sub-second deltas).
* Recording a sample is O(1): append to a fixed-size ring buffer. No
  allocation beyond the deque, no I/O, no lock contention worth worrying
  about (a short critical section under a per-registry lock).
* Percentiles are computed lazily, only when a snapshot is requested (for
  the API / UI), never on the hot path.
* The stage names are a closed vocabulary so the UI can rely on them.

The canonical pipeline this measures:

    T0 tick received -> T2 market state updated -> T4 signal ->
    T5 risk checked -> T6 order prepared -> T7 order dispatched ->
    T8 broker responded

    market_data      = T2 - T0
    strategy_eval    = T4 - T3
    risk             = T5 - T4
    order_prep       = T6 - T5
    order_dispatch   = T7 - T6
    broker_rtt       = T8 - T7        (EXTERNAL — Kite + network, not ours)
    internal_decision= T7 - T0        (tick -> order sent; our number)
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# Closed vocabulary — the frontend latency widget keys off these.
STAGE_MARKET_DATA = "market_data"
STAGE_STRATEGY_EVAL = "strategy_eval"
STAGE_RISK = "risk"
STAGE_ORDER_PREP = "order_prep"
STAGE_ORDER_DISPATCH = "order_dispatch"
STAGE_BROKER_RTT = "broker_rtt"
STAGE_INTERNAL_DECISION = "internal_decision"

INTERNAL_STAGES = (
    STAGE_MARKET_DATA,
    STAGE_STRATEGY_EVAL,
    STAGE_RISK,
    STAGE_ORDER_PREP,
    STAGE_ORDER_DISPATCH,
)
EXTERNAL_STAGES = (STAGE_BROKER_RTT,)

_DEFAULT_WINDOW = 2048


def _percentile(sorted_ms: list[float], pct: float) -> float:
    if not sorted_ms:
        return 0.0
    if len(sorted_ms) == 1:
        return sorted_ms[0]
    rank = pct / 100.0 * (len(sorted_ms) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_ms) - 1)
    frac = rank - lo
    return sorted_ms[lo] * (1.0 - frac) + sorted_ms[hi] * frac


@dataclass
class StageStats:
    stage: str
    count: int
    last_ms: float
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "stage": self.stage,
            "count": self.count,
            "last_ms": round(self.last_ms, 4),
            "avg_ms": round(self.avg_ms, 4),
            "min_ms": round(self.min_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "p50_ms": round(self.p50_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "p99_ms": round(self.p99_ms, 4),
        }


@dataclass
class _Ring:
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))
    last_ms: float = 0.0


class LatencyRegistry:
    """Process-local. One ring buffer of millisecond samples per stage."""

    def __init__(self, window: int = _DEFAULT_WINDOW) -> None:
        self._window = window
        self._rings: dict[str, _Ring] = {}
        self._lock = threading.Lock()

    def record_ns(self, stage: str, elapsed_ns: int) -> None:
        ms = elapsed_ns / 1_000_000.0
        with self._lock:
            ring = self._rings.get(stage)
            if ring is None:
                ring = _Ring(deque(maxlen=self._window))
                self._rings[stage] = ring
            ring.samples.append(ms)
            ring.last_ms = ms

    def record_ms(self, stage: str, elapsed_ms: float) -> None:
        self.record_ns(stage, int(elapsed_ms * 1_000_000))

    @contextmanager
    def span(self, stage: str) -> Iterator[None]:
        start = time.perf_counter_ns()
        try:
            yield
        finally:
            self.record_ns(stage, time.perf_counter_ns() - start)

    def stats(self, stage: str) -> StageStats | None:
        with self._lock:
            ring = self._rings.get(stage)
            samples = list(ring.samples) if ring else []
            last_ms = ring.last_ms if ring else 0.0
        if not samples:
            return None
        ordered = sorted(samples)
        return StageStats(
            stage=stage,
            count=len(samples),
            last_ms=last_ms,
            avg_ms=sum(samples) / len(samples),
            min_ms=ordered[0],
            max_ms=ordered[-1],
            p50_ms=_percentile(ordered, 50),
            p95_ms=_percentile(ordered, 95),
            p99_ms=_percentile(ordered, 99),
        )

    def snapshot(self) -> dict[str, object]:
        """Everything the API / UI needs. Cheap enough to call once per
        worker tick; NOT something to call per event."""
        stages: dict[str, dict[str, float | int | str]] = {}
        with self._lock:
            known = list(self._rings)
        for stage in known:
            s = self.stats(stage)
            if s is not None:
                stages[stage] = s.as_dict()

        internal = self.stats(STAGE_INTERNAL_DECISION)
        broker = self.stats(STAGE_BROKER_RTT)
        # "Idle" headline = the always-on cost of just processing data and
        # evaluating strategies, even when no order is produced.
        md = self.stats(STAGE_MARKET_DATA)
        se = self.stats(STAGE_STRATEGY_EVAL)
        idle_ms = (md.last_ms if md else 0.0) + (se.last_ms if se else 0.0)

        return {
            "stages": stages,
            "headline": {
                # what the compact "⚡ x.x ms" shows
                "idle_ms": round(idle_ms, 4),
                "internal_decision_ms": round(internal.last_ms, 4) if internal else None,
                "internal_decision_p95_ms": round(internal.p95_ms, 4) if internal else None,
                "broker_rtt_ms": round(broker.last_ms, 4) if broker else None,
            },
        }

    def reset(self) -> None:  # test hook
        with self._lock:
            self._rings.clear()


# Process-global registry. The worker records into it; a single-process
# deployment reads straight from it, a multi-process one goes via telemetry.
LATENCY = LatencyRegistry()

"""Live-trading engine building blocks (Phase 0, all Python).

This package holds the pieces that sit on the live decision path and must be
measured and kept off the database:

- ``latency``   — monotonic, per-stage latency instrumentation + percentiles.
- ``telemetry`` — publish/read a compact engine snapshot across processes
  (Redis when available, in-process fallback otherwise).

Later slices add: an in-memory market-state + incremental indicator engine,
a WebSocket tick feed, an order state machine with broker reconciliation,
and circuit breakers. See docs / the Phase 0 plan.
"""

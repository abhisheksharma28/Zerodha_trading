"""GET /monitoring/latency contract."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.live import telemetry
from app.live.latency import LATENCY, STAGE_MARKET_DATA, STAGE_STRATEGY_EVAL
from app.main import app


def _get():
    with TestClient(app) as client:
        return client.get("/api/v1/monitoring/latency")


def test_latency_endpoint_returns_thresholds_even_when_idle():
    LATENCY.reset()
    telemetry.reset()
    resp = _get()
    assert resp.status_code == 200
    body = resp.json()
    assert "thresholds_ms" in body
    assert set(body["thresholds_ms"]) == {"excellent", "fast", "moderate", "high"}
    assert body["source"] in {"redis", "in_process"}


def test_latency_endpoint_surfaces_recorded_stages_in_process():
    LATENCY.reset()
    telemetry.reset()
    telemetry._disabled_until = time.time() + 3600  # force the in-process fallback path
    LATENCY.record_ms(STAGE_MARKET_DATA, 0.15)
    LATENCY.record_ms(STAGE_STRATEGY_EVAL, 0.09)

    body = _get().json()
    assert body["available"] is True
    assert body["source"] == "in_process"
    stages = body["latency"]["stages"]
    assert STAGE_MARKET_DATA in stages
    assert stages[STAGE_MARKET_DATA]["last_ms"] == 0.15
    assert body["latency"]["headline"]["idle_ms"] == 0.24

    LATENCY.reset()
    telemetry.reset()

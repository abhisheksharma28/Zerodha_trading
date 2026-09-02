"""ServerTimingMiddleware: every API response carries handler timing, and
the latency registry gets an `api` sample."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.live.latency import LATENCY, STAGE_API
from app.main import app


def test_server_timing_header_and_api_stage():
    LATENCY.reset()
    with TestClient(app) as client:
        resp = client.get("/api/v1/monitoring/latency")

    assert resp.status_code == 200
    st = resp.headers.get("server-timing")
    assert st is not None and st.startswith("app;dur=")
    dur = float(st.split("=")[1])
    assert dur >= 0.0

    api = LATENCY.stats(STAGE_API)
    assert api is not None and api.count >= 1
    LATENCY.reset()

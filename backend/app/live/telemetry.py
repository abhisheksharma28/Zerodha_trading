"""Cross-process publish/read of the live-engine snapshot.

The strategy-evaluation worker runs in its own process (``app.workers.main``),
so its in-memory ``LATENCY`` registry is invisible to the API process that
serves ``GET /monitoring/latency``. This module bridges that gap:

* the worker calls :func:`publish` once per tick (off the critical path),
* the API calls :func:`read` to serve the UI.

Transport is Redis (already a declared dependency and configured via
``settings.redis_url``). If Redis is unavailable — e.g. a minimal Railway
deployment without a Redis add-on — both calls degrade quietly: ``publish``
is a no-op and ``read`` falls back to this process's own ``LATENCY``
snapshot (correct when the worker and API are the same process, empty
otherwise). Nothing on the trading path depends on this working.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.live.latency import LATENCY

logger = get_logger(__name__)

_KEY = "live:engine:snapshot"
_TTL_SECONDS = 15
_CONNECT_TIMEOUT = 0.25
_SOCKET_TIMEOUT = 0.25
_RETRY_BACKOFF_SECONDS = 60.0

_client: Any = None
_disabled_until = 0.0
_logged_unavailable = False


def _mark_unavailable(exc: Exception) -> None:
    global _disabled_until, _logged_unavailable
    _disabled_until = time.time() + _RETRY_BACKOFF_SECONDS
    if not _logged_unavailable:
        logger.info("live_telemetry_redis_unavailable", error=str(exc))
        _logged_unavailable = True


def _redis() -> Any | None:
    global _client
    if time.time() < _disabled_until:
        return None
    if _client is not None:
        return _client
    try:
        import redis  # declared dependency

        _client = redis.Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=_CONNECT_TIMEOUT,
            socket_timeout=_SOCKET_TIMEOUT,
        )
        return _client
    except Exception as exc:  # noqa: BLE001 - Redis is optional; never fatal
        _mark_unavailable(exc)
        return None


def publish(engine: dict[str, Any] | None = None) -> None:
    """Serialize the current latency snapshot (+ optional engine/health
    fields) and store it with a short TTL. Safe to call every tick."""
    payload = {
        "updated_epoch": time.time(),
        "latency": LATENCY.snapshot(),
        "engine": engine or {},
    }
    r = _redis()
    if r is None:
        return
    try:
        r.set(_KEY, json.dumps(payload), ex=_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        _mark_unavailable(exc)


def read() -> dict[str, Any]:
    """Return the freshest engine snapshot for the API. Shape:

        {available, source, stale, updated_epoch, latency: {...}, engine: {...}}
    """
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_KEY)
            if raw:
                data = json.loads(raw)
                age = time.time() - float(data.get("updated_epoch", 0))
                return {
                    "available": True,
                    "source": "redis",
                    "stale": age > _TTL_SECONDS,
                    "age_seconds": round(age, 2),
                    **data,
                }
        except Exception as exc:  # noqa: BLE001
            _mark_unavailable(exc)

    # Fallback: this process's own registry (true when API == worker process).
    local = LATENCY.snapshot()
    has_data = bool(local.get("stages"))
    return {
        "available": has_data,
        "source": "in_process",
        "stale": False,
        "age_seconds": 0.0,
        "updated_epoch": time.time(),
        "latency": local,
        "engine": {},
    }


def reset() -> None:  # test hook
    global _client, _disabled_until, _logged_unavailable
    _client = None
    _disabled_until = 0.0
    _logged_unavailable = False

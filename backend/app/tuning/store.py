"""On-disk cache for tuning results (one JSON per slug)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_DIR = Path(os.getenv("TUNING_CACHE_DIR", ".tuning_cache"))


def load(slug: str) -> dict[str, Any] | None:
    p = _DIR / f"{slug}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def save(slug: str, payload: dict[str, Any]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "cached_at": time.time()}
    fd, tmp = tempfile.mkstemp(dir=_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, _DIR / f"{slug}.json")
    finally:
        Path(tmp).unlink(missing_ok=True)

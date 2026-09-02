"""On-disk cache for robustness results (one JSON per slug)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_DIR = Path(os.getenv("ROBUSTNESS_CACHE_DIR", ".robustness_cache"))


def load(slug: str, kind: str = "robustness") -> dict[str, Any] | None:
    p = _DIR / (f"{slug}.json" if kind == "robustness" else f"{slug}.{kind}.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def save(slug: str, payload: dict[str, Any], kind: str = "robustness") -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "cached_at": time.time()}
    name = f"{slug}.json" if kind == "robustness" else f"{slug}.{kind}.json"
    fd, tmp = tempfile.mkstemp(dir=_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, _DIR / name)
    finally:
        Path(tmp).unlink(missing_ok=True)

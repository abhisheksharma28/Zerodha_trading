"""On-disk cache for canonical backtest results.

A backtest of NIFTY 100 over 3 years is expensive; the leaderboard reads
these cached JSON blobs and only re-runs on an explicit refresh. One file
per (slug, config_hash) so a config change naturally invalidates the old
result.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_DIR = Path(os.getenv("LEADERBOARD_CACHE_DIR", ".leaderboard_cache"))


def _path(slug: str, config_hash: str) -> Path:
    return _DIR / f"{slug}__{config_hash}.json"


def load(slug: str, config_hash: str) -> dict[str, Any] | None:
    p = _path(slug, config_hash)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def save(slug: str, config_hash: str, payload: dict[str, Any]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "cached_at": time.time()}
    p = _path(slug, config_hash)
    fd, tmp = tempfile.mkstemp(dir=_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, p)
    finally:
        Path(tmp).unlink(missing_ok=True)


def load_any(slug: str) -> dict[str, Any] | None:
    """Most-recent cached result for a slug regardless of config hash."""
    if not _DIR.exists():
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for f in _DIR.glob(f"{slug}__*.json"):
        try:
            blob = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        ts = float(blob.get("cached_at", 0))
        if best is None or ts > best[0]:
            best = (ts, blob)
    return best[1] if best else None

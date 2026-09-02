"""On-disk cache for Chinese Transformer research runs + model artifacts."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_DIR = Path(os.getenv("CHINESE_TRANSFORMER_CACHE_DIR", ".chinese_transformer_cache"))


def _p(kind: str, key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return _DIR / f"{kind}__{safe}.json"


def load(kind: str, key: str) -> dict[str, Any] | None:
    p = _p(kind, key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def save(kind: str, key: str, payload: dict[str, Any]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "cached_at": time.time()}
    fd, tmp = tempfile.mkstemp(dir=_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, default=str)
        os.replace(tmp, _p(kind, key))
    finally:
        Path(tmp).unlink(missing_ok=True)


def list_kind(kind: str) -> list[dict[str, Any]]:
    if not _DIR.exists():
        return []
    out = []
    for f in sorted(_DIR.glob(f"{kind}__*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (ValueError, OSError):
            continue
    return out

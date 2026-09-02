"""Adopted tuned presets.

Populated after reviewing ``run_tuning`` output. Each entry is a dict of
parameter overrides layered on top of the strategy's ``balanced`` preset
by the canonical leaderboard run and by ``ensure_paper_deployments``.

Empty is a valid, honest state: if grid search finds no combo that beats
the preset on the *worse* of the in-sample / out-of-sample halves, nothing
is adopted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Baked-in adoptions (reviewed + committed). The runtime file below
# (written by the "Adopt tuned preset" button) is merged on top.
TUNED_PRESETS: dict[str, dict[str, Any]] = {
    # slug: {"param": value, ...}
}

_RUNTIME = Path(os.getenv("TUNING_CACHE_DIR", ".tuning_cache")) / "adopted.json"


def _runtime_adopted() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_RUNTIME.read_text())
    except (OSError, ValueError):
        return {}


def tuned_overrides(slug: str) -> dict[str, Any]:
    merged = dict(TUNED_PRESETS.get(slug, {}))
    merged.update(_runtime_adopted().get(slug, {}))
    return merged


def set_runtime_adoption(slug: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Persist (or clear, with ``None``) a runtime adoption for one slug."""
    _RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    data = _runtime_adopted()
    if overrides:
        data[slug] = overrides
    else:
        data.pop(slug, None)
    _RUNTIME.write_text(json.dumps(data, indent=2))
    return data.get(slug, {})

"""Out-of-process runner for the leaderboard canonical refresh.

``POST /leaderboard/refresh`` used to call ``refresh_all`` synchronously
*inside the single web worker* — a 20-30 minute CPU job that made the whole
API unresponsive (and dead-locked ``--reload``). Now the endpoint spawns
this module as a detached child process; it writes progress to a status
JSON that ``GET /leaderboard/refresh/status`` reads.

Run directly:  ``python -m app.leaderboard.refresh_runner [slug ...]``
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "leaderboard_refresh_status.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def run(slugs: list[str], *, status_path: Path = STATUS_PATH) -> dict[str, Any]:
    """Refresh ``slugs`` (empty = the whole canonical suite), updating the
    status file after every strategy. Returns the final status dict."""
    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.leaderboard.config import CANONICAL
    from app.leaderboard.service import run_canonical

    targets = slugs or list(CANONICAL)
    started = time.monotonic()
    status: dict[str, Any] = {
        "state": "running", "pid": os.getpid(), "started_at": _now(), "updated_at": _now(),
        "total": len(targets), "completed": 0, "current": None,
        "results": {}, "elapsed_s": 0.0,
    }
    _write(status_path, status)

    settings = get_settings()
    db = SessionLocal()
    try:
        for slug in targets:
            status["current"] = slug
            status["updated_at"] = _now()
            status["elapsed_s"] = round(time.monotonic() - started, 1)
            _write(status_path, status)
            if slug not in CANONICAL:
                status["results"][slug] = "skipped: not in canonical suite"
            else:
                try:
                    payload = run_canonical(db, settings, slug)
                    m = payload.get("metrics", {})
                    status["results"][slug] = (
                        f"ok: return {m.get('return_pct')}%, sharpe {m.get('sharpe_ratio')}, "
                        f"{m.get('total_trades')} trades"
                        + (" [RUINED]" if payload.get("ruined") else "")
                    )
                except Exception as exc:  # noqa: BLE001 - one bad strategy must not stop the batch
                    status["results"][slug] = f"error: {exc}"
            status["completed"] += 1
        status["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        status["state"] = "error"
        status["error"] = str(exc)
    finally:
        db.close()
        status["current"] = None
        status["updated_at"] = _now()
        status["elapsed_s"] = round(time.monotonic() - started, 1)
        _write(status_path, status)
    return status


if __name__ == "__main__":
    run(sys.argv[1:])

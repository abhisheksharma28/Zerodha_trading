"""Start / inspect the out-of-process leaderboard refresh (see refresh_runner)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import ConflictError
from app.leaderboard.refresh_runner import STATUS_PATH

_LOG_PATH = STATUS_PATH.with_name("leaderboard_refresh.log")


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    return True


def read_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {"state": "idle"}
    try:
        s = json.loads(STATUS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"state": "idle"}
    # a "running" status whose process is gone never finished cleanly
    if s.get("state") == "running" and not _pid_alive(s.get("pid")):
        s["state"] = "stalled"
        s["note"] = "the refresh process is no longer running; start a new one."
    return s


def is_running() -> bool:
    return read_status().get("state") == "running"


def start_refresh(slugs: list[str] | None = None) -> dict[str, Any]:
    if is_running():
        cur = read_status()
        raise ConflictError(
            f"A leaderboard refresh is already running "
            f"({cur.get('completed', 0)}/{cur.get('total', '?')} done).",
            details={"status": cur},
        )
    args = [sys.executable, "-m", "app.leaderboard.refresh_runner", *(slugs or [])]
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a") as log:
        log.write(f"\n--- refresh started {datetime.now(UTC).isoformat()} slugs={slugs or 'ALL'} ---\n")
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            cwd=str(STATUS_PATH.parent.parent),
        )
    seed = {
        "state": "running", "pid": proc.pid, "started_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "total": len(slugs) if slugs else None, "completed": 0, "current": None, "results": {},
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(seed, indent=2))
    return {
        "job": "started", "pid": proc.pid, "slugs": slugs or "all",
        "status_url": "/api/v1/leaderboard/refresh/status",
        "log": str(_LOG_PATH),
    }

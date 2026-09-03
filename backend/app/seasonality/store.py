"""Persisted seasonality report + walk-forward backtests.

``analyze()`` takes ~50s (bootstrap over the whole grid), so the API reads
a pre-built ``data/seasonality_report.json``. Rebuild with
``python -m app.seasonality.store`` or ``POST /seasonality/refresh``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "seasonality_report.json"
STATUS_PATH = Path(__file__).resolve().parents[2] / "data" / "seasonality_status.json"


def build(db: Any, settings: Any) -> dict[str, Any]:
    from app.seasonality.backtest import run_all_strategies
    from app.seasonality.engine import analyze

    _write_status("running", note="analyze()")
    report = analyze(db, settings, bootstrap=True)
    _write_status("running", note="walk-forward backtests")
    report["backtests"] = run_all_strategies(db, settings, start_test_year=2012)
    report["built_at"] = datetime.now(UTC).isoformat()

    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(report))
    _write_status("done", note=f"{report['sector_count']} sectors, verdict: {report['verdict']}")
    return report


def load() -> dict[str, Any] | None:
    if not STORE_PATH.exists():
        return None
    try:
        return json.loads(STORE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_status(state: str, *, note: str = "") -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({
        "state": state, "note": note, "pid": os.getpid(),
        "updated_at": datetime.now(UTC).isoformat(),
    }))


def read_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {"state": "idle"}
    try:
        st = json.loads(STATUS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"state": "idle"}
    pid = st.get("pid")
    if st.get("state") == "running" and pid and not _alive(pid):
        st["state"] = "stalled"
    return st


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    return True


def start_refresh() -> dict[str, Any]:
    cur = read_status()
    if cur.get("state") == "running":
        raise RuntimeError("a seasonality refresh is already running")
    log = open(STORE_PATH.parent / "seasonality_refresh.log", "a")  # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.seasonality.store"],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    _write_status("running", note="spawned")
    return {"job": "seasonality-refresh", "pid": proc.pid}


if __name__ == "__main__":
    from app.config import get_settings
    from app.db.session import SessionLocal

    _db = SessionLocal()
    try:
        build(_db, get_settings())
    finally:
        _db.close()
    print(f"wrote {STORE_PATH}")

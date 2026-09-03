"""Child-process entry point for the strategy sandbox.

Invoked as ``python -m app.strategy_editor.worker <tmpdir>`` by
``sandbox.run_job``. Reads ``<tmpdir>/job.json``, does the work, writes
``<tmpdir>/result.json``. rlimits are already applied by the parent's
``preexec_fn``; everything here is best-effort and must never hang.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    d = Path(sys.argv[1])
    result = d / "result.json"
    try:
        job = json.loads((d / "job.json").read_text())
        from app.strategy_editor.execute import execute

        payload = execute(job)
    except Exception as exc:  # noqa: BLE001 - any failure becomes a clean result
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "stage": "worker"}
    try:
        result.write_text(json.dumps(payload, default=str))
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

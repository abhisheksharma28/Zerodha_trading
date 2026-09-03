"""Optional helper: pull a Kaggle options-history dataset into the folder
``local_history`` reads from.

Requires the ``kaggle`` CLI (``pip install kaggle``) and credentials at
``~/.kaggle/kaggle.json`` (Account → Create New API Token on kaggle.com).
Nothing here runs automatically; call ``fetch(slug)`` once, then run a
backtest with ``data_source="local"``.

Known NSE index-option history datasets (verify licence + freshness on
Kaggle before use; schemas vary — the local loader maps columns loosely):
  * "debashis74017/nifty-bank-nifty-option-chain-data-2022-2023"
  * "gopalmahadevan/nifty-options-chain-data"
  * "sohambhutkar/nifty-50-options-data"
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app.adaptive_options.local_history import _DIR as _HISTORY_DIR


def kaggle_available() -> tuple[bool, str]:
    if shutil.which("kaggle") is None:
        return False, "The `kaggle` CLI is not installed (`pip install kaggle`)."
    cred = Path(os.path.expanduser("~/.kaggle/kaggle.json"))
    if not cred.exists():
        return False, "No ~/.kaggle/kaggle.json — create an API token on kaggle.com."
    return True, "ready"


def fetch(slug: str, *, dest: Path | None = None, unzip: bool = True) -> dict[str, str]:
    """Download a Kaggle dataset ``owner/name`` into ``dest`` (default: the
    history dir). Returns a small status dict; raises on CLI failure."""
    ok, why = kaggle_available()
    if not ok:
        return {"ok": "false", "reason": why}
    out = dest or (_HISTORY_DIR / slug.split("/")[-1])
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "datasets", "download", "-d", slug, "-p", str(out)]
    if unzip:
        cmd.append("--unzip")
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)  # noqa: S603
    if res.returncode != 0:
        return {"ok": "false", "reason": (res.stderr or res.stdout or "kaggle CLI failed").strip()}
    files = sorted(p.name for p in out.glob("**/*") if p.is_file())
    return {"ok": "true", "path": str(out), "files": ", ".join(files[:20]),
            "note": "Move / rename the CSVs to <history_dir>/<UNDERLYING>.csv or "
                    "<history_dir>/<UNDERLYING>/<YYYY-MM-DD>.csv, then run a backtest "
                    "with data_source='local'."}

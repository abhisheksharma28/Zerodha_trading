"""Two-layer guard for user-authored strategy code.

1. A static AST check rejects imports outside a small allow-list and any
   obviously dangerous builtin / dunder use *before* the code is ever run.
2. Execution happens only in a short-lived child process
   (``app.strategy_editor.worker``) with CPU / address-space / process
   rlimits applied in a ``preexec_fn``, plus a wall-clock timeout on the
   parent side.

This is a pragmatic boundary for a single-operator tool, not a hostile-
multi-tenant sandbox. Full isolation (namespaces / container) is the next
step if untrusted third parties ever get to run code here.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# modules a strategy may import (root package name)
_ALLOWED_IMPORT_ROOTS = {
    "math", "statistics", "cmath", "random", "datetime", "time", "collections",
    "itertools", "functools", "typing", "dataclasses", "enum", "heapq", "bisect",
    "decimal", "fractions", "numbers", "re", "json", "string", "operator",
    "app",  # our own package (indicators / BaseStrategy / TemplateStrategy)
}
_BLOCKED_CALLS = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "memoryview", "getattr", "setattr", "delattr",
}
_BLOCKED_ATTRS = {
    "__globals__", "__subclasses__", "__bases__", "__mro__", "__builtins__",
    "__code__", "__closure__", "__dict__", "__reduce__", "__reduce_ex__",
    "__getattribute__", "__class__", "__self__", "__func__", "__wrapped__",
}

_CPU_SECONDS = 30
_ADDRESS_SPACE = 1_800 * 1024 * 1024   # 1.8 GB
_WALL_TIMEOUT = 75


class SandboxError(ValueError):
    """The code was rejected by the static check or the worker failed."""


def check_source(src: str) -> None:
    """Raise :class:`SandboxError` if the source is syntactically bad or uses
    something outside the allow-list. Runs nothing."""
    if len(src) > 200_000:
        raise SandboxError("Strategy source is too large (200 KB limit).")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise SandboxError(f"SyntaxError: line {exc.lineno}: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _ALLOWED_IMPORT_ROOTS:
                    raise SandboxError(f"import of '{alias.name}' is not allowed here")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root and root not in _ALLOWED_IMPORT_ROOTS:
                raise SandboxError(f"'from {node.module} import ...' is not allowed here")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BLOCKED_CALLS:
                raise SandboxError(f"call to '{node.func.id}()' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            raise SandboxError(f"access to '{node.attr}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in _BLOCKED_CALLS:
            raise SandboxError(f"use of '{node.id}' is not allowed")


def _apply_rlimits() -> None:  # pragma: no cover - runs in the child, pre-exec
    # every limit is best-effort: not all are enforced on every OS (macOS
    # rejects RLIMIT_AS, for one). A missing limit must never abort the spawn.
    limits = [
        (getattr(resource, "RLIMIT_CPU", None), (_CPU_SECONDS, _CPU_SECONDS + 2)),
        (getattr(resource, "RLIMIT_AS", None), (_ADDRESS_SPACE, _ADDRESS_SPACE)),
        (getattr(resource, "RLIMIT_DATA", None), (_ADDRESS_SPACE, _ADDRESS_SPACE)),
        (getattr(resource, "RLIMIT_NPROC", None), (96, 96)),
        (getattr(resource, "RLIMIT_FSIZE", None), (64 * 1024 * 1024, 64 * 1024 * 1024)),
    ]
    for lim, val in limits:
        if lim is not None:
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(lim, val)


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    """Validate the source, then run ``job`` in a rlimited child process.
    ``job['mode']`` is ``'validate'`` or ``'backtest'``. Always returns a
    dict with at least ``{'ok': bool}``."""
    src = job.get("source", "")
    try:
        check_source(src)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc), "stage": "static-check"}

    with tempfile.TemporaryDirectory(prefix="stratedit_") as d:
        (Path(d) / "job.json").write_text(json.dumps(job))
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "app.strategy_editor.worker", d],
                capture_output=True, text=True, timeout=_WALL_TIMEOUT,
                preexec_fn=_apply_rlimits,  # noqa: PLW1509 - POSIX only, intended
                env={**os.environ, "STRATEGY_EDITOR_CHILD": "1"},
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timed out after {_WALL_TIMEOUT}s", "stage": "run"}

        out = Path(d) / "result.json"
        if out.exists():
            try:
                return json.loads(out.read_text())
            except ValueError:
                pass
        tail = (proc.stderr or proc.stdout or "worker produced no output").strip()[-3000:]
        rc = proc.returncode
        hint = " (likely hit the memory or CPU limit)" if rc and rc < 0 else ""
        return {"ok": False, "error": f"worker exited {rc}{hint}:\n{tail}", "stage": "run"}

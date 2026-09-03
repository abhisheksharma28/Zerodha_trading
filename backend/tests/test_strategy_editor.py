"""The in-app Python strategy editor: static safety check + sandboxed
validate. (The backtest path needs a broker session and is covered by the
adhoc backtest tests.)"""

from __future__ import annotations

import pytest

from app.strategy_editor import execute, sandbox, service

# --------------------------------------------------------------------------
# static AST guard
# --------------------------------------------------------------------------

def test_check_source_accepts_the_starter():
    sandbox.check_source(execute.starter_source())


@pytest.mark.parametrize(
    "src",
    [
        "import os\nos.system('id')",
        "import subprocess",
        "from socket import socket",
        "import requests",
        "open('/etc/passwd').read()",
        "eval('2+2')",
        "x = (1).__class__.__bases__",
        "y = ().__class__.__subclasses__()",
        "def f():\n    return 1\nf.__globals__",
    ],
)
def test_check_source_rejects_dangerous_code(src):
    with pytest.raises(sandbox.SandboxError):
        sandbox.check_source(src)


def test_check_source_reports_syntax_errors():
    with pytest.raises(sandbox.SandboxError, match="SyntaxError"):
        sandbox.check_source("def broken(:\n  pass")


def test_check_source_allows_maths_and_indicators():
    sandbox.check_source(
        "import math\nfrom app.strategies.indicators import ema, rsi\n"
        "from app.strategies.library.base import TemplateStrategy\n"
        "z = math.sqrt(2)\n"
    )


# --------------------------------------------------------------------------
# sandboxed validate (spawns the worker subprocess)
# --------------------------------------------------------------------------

def test_validate_starter_returns_its_schema():
    res = service.validate(execute.starter_source())
    assert res["ok"] is True
    assert res["name"] == "My EMA Cross"
    assert "fast" in res["params"] and "slow" in res["params"]
    assert set(res["presets"]) == {"conservative", "balanced", "aggressive"}
    assert "1d" in res["supported_timeframes"]


def test_validate_rejects_a_non_template_class():
    src = (
        "from app.strategies.base import BaseStrategy\n"
        "class Strategy(BaseStrategy):\n"
        "    def on_bar(self, bar):\n        pass\n"
    )
    res = service.validate(src)
    assert res["ok"] is False
    assert "TemplateStrategy" in res["error"]


def test_validate_blocks_a_forbidden_import_before_running():
    res = service.validate("import socket\nclass Strategy: pass\n")
    assert res["ok"] is False and res["stage"] == "static-check"


def test_starter_payload_has_the_api_cheatsheet():
    s = service.starter()
    assert s["entry_point"] == "Strategy"
    assert "on_bar" in s["api"] and s["api"]["allowed_imports"]

"""Loads a StrategyVersion's source_code into a BaseStrategy subclass.

Uses a restricted exec() namespace — user strategy code runs in-process (not
sandboxed at the OS level yet; see TODO below), so this is a convenience
loader, not a security boundary. If/when third-party or untrusted strategy
code is ever supported, this must move to a subprocess/container sandbox
before that happens — tracked here deliberately so it isn't forgotten.
"""

import types

from app.core.exceptions import ValidationError
from app.strategies.base import BaseStrategy


def load_strategy_class(source_code: str, entry_point: str) -> type[BaseStrategy]:
    module = types.ModuleType("user_strategy")
    try:
        exec(compile(source_code, filename="<strategy>", mode="exec"), module.__dict__)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a validation error
        raise ValidationError(f"Strategy source failed to compile/execute: {exc}") from exc

    strategy_cls = getattr(module, entry_point, None)
    if strategy_cls is None or not (
        isinstance(strategy_cls, type) and issubclass(strategy_cls, BaseStrategy)
    ):
        raise ValidationError(
            f"Entry point '{entry_point}' not found or is not a BaseStrategy subclass."
        )
    return strategy_cls

"""API-facing layer for the in-app Python strategy editor."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.schemas.strategy import StrategyCreate, StrategyVersionCreate
from app.services import strategy_service
from app.strategy_editor import execute as _exec
from app.strategy_editor import sandbox


def starter() -> dict[str, Any]:
    """A working starter strategy + the API surface it may use."""
    return {
        "source": _exec.starter_source(),
        "entry_point": "Strategy",
        "api": {
            "base_class": "app.strategies.library.base.TemplateStrategy",
            "must_define": "exactly one TemplateStrategy subclass named `Strategy`",
            "on_bar": "def on_bar(self, bar: Bar) -> None  — called once per closed bar",
            "helpers": [
                "self.ingest(bar) -> InstrumentBuffer (buf.closes / highs / lows / volumes / bars)",
                "self.p['name'] — resolved parameter value",
                "self.submit(symbol, 'BUY'|'SELL', qty, exchange=, product=)",
                "self.rebalance_to(symbol, target_qty, exchange=, product=)",
                "self.size_position(price, stop_distance=?, symbol=?) -> int",
                "self.position(symbol) -> int, self.long_entries_allowed() -> bool",
            ],
            "indicators": "from app.strategies.indicators import ema, sma, rsi, macd, atr, "
                          "bollinger, zscore, adx, roc, vwap, crossed_above, crossed_below",
            "allowed_imports": "math, statistics, datetime, random, collections, itertools, "
                               "functools, typing, dataclasses, enum, re, json, and app.*",
            "limits": "runs in a subprocess: 30s CPU, ~1.8 GB RAM, 75s wall clock, no network / files",
        },
    }


def validate(source: str, entry_point: str = "Strategy") -> dict[str, Any]:
    res = sandbox.run_job({"mode": "validate", "source": source, "entry_point": entry_point})
    return res


def backtest(payload: dict[str, Any]) -> dict[str, Any]:
    job = {"mode": "backtest", **payload}
    if not job.get("source"):
        raise ValidationError("source is required")
    if not job.get("symbols"):
        raise ValidationError("pick at least one instrument")
    return sandbox.run_job(job)


def save(db: Session, *, source: str, entry_point: str, name: str,
         description: str = "") -> dict[str, Any]:
    """Persist a validated editor strategy as a normal Strategy + first
    version (so it shows up in My Strategies / Backtests / deploy)."""
    check = validate(source, entry_point)
    if not check.get("ok"):
        raise ValidationError(check.get("error", "strategy failed validation"))
    payload = StrategyCreate(
        name=name or check.get("name") or "Custom strategy",
        description=description or f"Authored in the Python editor ({check.get('slug')})",
        initial_version=StrategyVersionCreate(
            source_code=source, parameters={}, entry_point=entry_point,
            change_summary="Created in the Python strategy editor",
        ),
    )
    strat = strategy_service.create_strategy(db, payload)
    return {"ok": True, "strategy_id": str(strat.id), "name": strat.name}

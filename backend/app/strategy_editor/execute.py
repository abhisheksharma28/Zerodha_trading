"""The work done inside the sandbox child: load the user's class, and
either report its parameter schema (``validate``) or run a backtest
(``backtest``) through the same engine the library templates use.
"""

from __future__ import annotations

from typing import Any

from app.strategies.library.base import TemplateStrategy

_STARTER = '''\
"""My strategy. It must define exactly one TemplateStrategy subclass named
`Strategy` (the entry point). See the API cheat-sheet in the editor panel."""

from typing import ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import ema
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class Strategy(TemplateStrategy):
    SLUG: ClassVar[str] = "my-ema-cross"
    NAME: ClassVar[str] = "My EMA Cross"
    CATEGORY: ClassVar[str] = "Custom"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "fast": ParamSpec("integer", 20, "Fast EMA.", min=2, max=200),
        "slow": ParamSpec("integer", 50, "Slow EMA.", min=3, max=400),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }
    PRESETS: ClassVar[dict[str, dict]] = {
        "conservative": preset(fast=30, slow=100, sizing_method="fixed_quantity", fixed_quantity=5),
        "balanced": preset(fast=20, slow=50, sizing_method="fixed_quantity", fixed_quantity=10),
        "aggressive": preset(fast=9, slow=21, sizing_method="fixed_quantity", fixed_quantity=15),
    }
    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description="Long when the fast EMA is above the slow EMA, flat otherwise.",
        logic="Compute EMA(fast) and EMA(slow) each bar; hold 1 unit long while fast > slow.",
        timeframe="day / 60m / 15m", market_types=["NSE equities"],
        supports_long=True, supports_short=False, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False, complexity="Low", time_horizon="Swing",
        risks=["A simple crossover whipsaws in range-bound markets."],
        best_for="Trending names.", warning="Not guaranteed profitable; validate out-of-sample.",
        required_data=["OHLCV bars per instrument"],
        example="On daily bars: EMA20 crosses above EMA50 -> go long; crosses below -> flat.",
    )

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        closes = list(buf.closes)
        if len(closes) < int(self.p["slow"]) + 2:
            return
        fast = ema(closes, int(self.p["fast"]))
        slow = ema(closes, int(self.p["slow"]))
        if fast is None or slow is None:
            return
        want = 10 if fast > slow else 0
        if want and not self.long_entries_allowed():
            want = 0
        self.rebalance_to(bar.instrument, want if want else 0,
                          exchange=self.p["exchange"], product=self.p["product"])
'''


def starter_source() -> str:
    return _STARTER


def _load_class(source: str, entry_point: str) -> type[TemplateStrategy]:
    from app.strategies.registry import load_strategy_class

    cls = load_strategy_class(source, entry_point)
    if not issubclass(cls, TemplateStrategy):
        raise TypeError(
            f"'{entry_point}' must subclass TemplateStrategy (so it has PARAMS / PRESETS / "
            "METADATA and works with the backtest + deploy plumbing)."
        )
    return cls


def _validate(job: dict[str, Any]) -> dict[str, Any]:
    cls = _load_class(job["source"], job.get("entry_point", "Strategy"))
    presets = cls.presets()
    return {
        "ok": True,
        "mode": "validate",
        "entry_point": job.get("entry_point", "Strategy"),
        "name": cls.NAME,
        "slug": cls.SLUG,
        "category": cls.CATEGORY,
        "supported_timeframes": list(cls.SUPPORTED_TIMEFRAMES),
        "min_instruments": cls.MIN_INSTRUMENTS,
        "max_instruments": cls.MAX_INSTRUMENTS,
        "params": cls.parameter_schema(),
        "presets": sorted(presets),
    }


def _backtest(job: dict[str, Any]) -> dict[str, Any]:
    from app.backtesting.adhoc import run_adhoc
    from app.config import get_settings
    from app.db.session import SessionLocal

    cls = _load_class(job["source"], job.get("entry_point", "Strategy"))
    db = SessionLocal()
    try:
        report = run_adhoc(
            db, get_settings(),
            slug=cls.SLUG, template_cls=cls,
            symbols=list(job.get("symbols") or []),
            timeframe=job.get("timeframe", "1d"),
            start=job.get("start"), end=job.get("end"),
            preset=job.get("preset", "balanced"),
            capital=float(job.get("capital", 1_000_000.0)),
            overrides=job.get("overrides") or None,
            max_gross_exposure=float(job.get("max_gross_exposure", 1.0)),
        )
    finally:
        db.close()

    return {
        "ok": True,
        "mode": "backtest",
        "name": report.strategy_name,
        "timeframe": report.timeframe,
        "start": report.start,
        "end": report.end,
        "capital": report.capital,
        "used_symbols": report.used_symbols,
        "skipped": report.skipped,
        "parameters": report.parameters,
        "metrics": report.metrics,
        "charts": report.charts,
        "equity_curve": report.equity_curve,
        "per_symbol": [s.__dict__ for s in report.per_symbol],
        "trades": report.trades,
        "data_quality": report.data_quality,
        "caveats": report.caveats,
        "generated_at": report.generated_at,
    }


def execute(job: dict[str, Any]) -> dict[str, Any]:
    mode = job.get("mode", "validate")
    try:
        if mode == "validate":
            return _validate(job)
        if mode == "backtest":
            return _backtest(job)
        return {"ok": False, "error": f"unknown mode '{mode}'"}
    except Exception as exc:  # noqa: BLE001 - surfaced to the editor UI
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "mode": mode}

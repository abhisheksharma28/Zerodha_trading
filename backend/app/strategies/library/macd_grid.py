"""MACD Grid Accumulator — a MACD-trend-gated 1% averaging grid.

Adapted from the grid method popularised by Dr Reshampal Kaur: only build
the ladder while the MACD line sits above its signal line; add one rung
every ``grid_step_pct`` the price falls, sell one rung every
``grid_step_pct`` it recovers, and flatten the whole ladder when the MACD
line crosses back below its signal.

This deliberately averages *into* weakness, so an instrument that keeps
falling while MACD stays positive can build a large, underwater position.
Not guaranteed profitable — position sizing and the MACD exit are the only
risk controls. Validate out-of-sample before trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import macd
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Ladder:
    anchor: float                       # price the ladder opened at
    rungs: list[float] = field(default_factory=list)  # fill price of each open rung
    qty_per_rung: int = 0


class MacdGridStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "macd-grid"
    NAME: ClassVar[str] = "MACD Grid Accumulator"
    CATEGORY: ClassVar[str] = "Mean Reversion"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 15
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "30m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 40

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "macd_fast": ParamSpec("integer", 12, "MACD fast EMA.", min=2, max=100),
        "macd_slow": ParamSpec("integer", 26, "MACD slow EMA.", min=3, max=200),
        "macd_signal": ParamSpec("integer", 9, "MACD signal EMA.", min=2, max=100),
        "grid_step_pct": ParamSpec("number", 1.0,
                                   "Price move (%) between rungs: buy one on each step down, "
                                   "sell one on each step up.", min=0.1, max=10.0),
        "max_rungs": ParamSpec("integer", 6, "Most rungs the ladder may hold at once.",
                               min=1, max=50),
        "rung_qty": ParamSpec("integer", 0,
                              "Fixed quantity per rung. 0 = size from capital_allocation / "
                              "max_rungs / price (capped by max_position_size_pct).",
                              min=0, max=1_000_000, group="sizing"),
        "reference": ParamSpec("enum", "last_entry",
                               "Measure the next step from the last rung's fill (last_entry) "
                               "or from the ladder anchor (anchor).",
                               choices=("last_entry", "anchor"), group="core"),
        "require_macd_up": ParamSpec("boolean", True,
                                     "Only add rungs while the MACD line is above its signal.",
                                     group="filter"),
        "exit_on_macd_cross_down": ParamSpec("boolean", True,
                                             "Sell the entire ladder when the MACD line crosses "
                                             "below its signal.", group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            grid_step_pct=2.0, max_rungs=4, reference="anchor",
            require_macd_up=True, exit_on_macd_cross_down=True, product="CNC",
            sizing_method="fixed_capital", max_position_size_pct=20.0,
        ),
        "balanced": preset(
            grid_step_pct=1.0, max_rungs=6, reference="last_entry",
            require_macd_up=True, exit_on_macd_cross_down=True, product="CNC",
            sizing_method="fixed_capital", max_position_size_pct=30.0,
        ),
        "aggressive": preset(
            grid_step_pct=0.5, max_rungs=10, reference="last_entry",
            require_macd_up=True, exit_on_macd_cross_down=False, product="CNC",
            sizing_method="fixed_capital", max_position_size_pct=45.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "A MACD-gated averaging grid: while MACD is above its signal, buy a rung on every "
            "grid_step_pct fall and sell a rung on every grid_step_pct recovery; flatten the "
            "whole ladder on a MACD cross-down."
        ),
        logic=(
            "Per instrument: compute MACD(macd_fast, macd_slow, macd_signal). Histogram > 0 means "
            "the MACD line is above its signal. With no ladder open and the histogram positive, "
            "buy the first rung and set the anchor. With a ladder open, buy another rung (up to "
            "max_rungs) whenever price <= reference * (1 - grid_step_pct/100) and MACD is still up; "
            "sell the newest rung whenever price >= its fill * (1 + grid_step_pct/100). If "
            "exit_on_macd_cross_down, a histogram cross from >0 to <=0 sells every rung at once."
        ),
        timeframe="15minute / 30minute / 60minute / day",
        market_types=["NSE cash equities", "index / stock futures (NRML)"],
        supports_long=True, supports_short=False, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Swing",
        risks=[
            "Averages into a falling market — a persistent downtrend with MACD lag builds a large "
            "underwater position.",
            "Only max_rungs and the MACD cross-down cap the exposure; there is no hard stop.",
            "Frequent small round-trips make it sensitive to costs and slippage.",
        ],
        best_for="Range-bound or gently uptrending liquid names where dips mean-revert.",
        warning="This strategy adds size as price moves against it. Size the rungs conservatively.",
        required_data=["OHLCV bars per instrument, at least macd_slow + macd_signal + 2 bars"],
        example=(
            "On daily RELIANCE bars with MACD line above signal: buy rung 1 at 1500. Price falls "
            "1% to 1485 -> buy rung 2. Rises 1% from 1485 to ~1500 -> sell rung 2. MACD line "
            "crosses below signal -> sell rung 1. Mechanics only, not advice."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._ladders: dict[str, _Ladder] = {}
        self._prev_hist: dict[str, float] = {}

    def _rung_qty(self, price: float, sym: str) -> int:
        fixed = int(self.p["rung_qty"])
        if fixed > 0:
            return fixed
        base = self.size_position(price, symbol=sym)
        return max(1, base // max(1, int(self.p["max_rungs"])))

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        closes = list(buf.closes)
        need = int(self.p["macd_slow"]) + int(self.p["macd_signal"]) + 2
        if len(closes) < need:
            return

        m = macd(closes, int(self.p["macd_fast"]), int(self.p["macd_slow"]),
                 int(self.p["macd_signal"]))
        if m is None:
            return
        _line, _sig, hist = m
        prev_hist = self._prev_hist.get(sym, hist)
        self._prev_hist[sym] = hist

        price = closes[-1]
        step = float(self.p["grid_step_pct"]) / 100.0
        macd_up = hist > 0.0
        crossed_down = prev_hist > 0.0 >= hist
        ladder = self._ladders.get(sym)

        # --- full exit on a MACD cross-down ---
        if ladder is not None and self.p["exit_on_macd_cross_down"] and crossed_down:
            self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
            self._ladders.pop(sym, None)
            return

        # --- open the first rung ---
        if ladder is None:
            if not macd_up and self.p["require_macd_up"]:
                return
            if not self.long_entries_allowed():
                return
            qty = self._rung_qty(price, sym)
            if qty <= 0:
                return
            self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
            self._ladders[sym] = _Ladder(anchor=price, rungs=[price], qty_per_rung=qty)
            return

        # --- sell the newest rung on a step up ---
        if ladder.rungs and price >= ladder.rungs[-1] * (1.0 + step):
            self.submit(sym, "SELL", ladder.qty_per_rung,
                        exchange=self.p["exchange"], product=self.p["product"])
            ladder.rungs.pop()
            if not ladder.rungs:
                self._ladders.pop(sym, None)
            return

        # --- add a rung on a step down (trend still up) ---
        ref = ladder.rungs[-1] if self.p["reference"] == "last_entry" else ladder.anchor
        can_add = len(ladder.rungs) < int(self.p["max_rungs"])
        if can_add and price <= ref * (1.0 - step) and (macd_up or not self.p["require_macd_up"]):
            self.submit(sym, "BUY", ladder.qty_per_rung,
                        exchange=self.p["exchange"], product=self.p["product"])
            ladder.rungs.append(price)

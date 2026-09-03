"""Dual Momentum — relative rank plus an absolute-momentum on/off switch.

After Gary Antonacci's framework: each rebalance, rank the basket by its
trailing ``lookback`` return (relative momentum) and hold the top N
equal-weight — but only names whose own trailing return is also positive
(absolute momentum). When a top-ranked name fails the absolute test its
slot goes to cash, so the book de-risks in broad downturns.

Not guaranteed profitable. It is monthly and trend-dependent; whipsaws
around turning points and needs a real basket to diversify. Validate
out-of-sample with turnover costs.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class DualMomentumStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "dual-momentum"
    NAME: ClassVar[str] = "Dual Momentum"
    CATEGORY: ClassVar[str] = "Momentum"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 260

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "lookback": ParamSpec("integer", 252, "Trailing-return window (bars). ~252 = one year.",
                              min=20, max=750),
        "skip_recent": ParamSpec("integer", 0, "Skip the most recent N bars of the lookback "
                                 "(short-term reversal control).", min=0, max=60),
        "top_n": ParamSpec("integer", 3, "How many names to hold equal-weight.", min=1, max=50),
        "abs_min_return": ParamSpec("number", 0.0, "A held name's trailing return must exceed this "
                                    "% (absolute-momentum gate).", min=-50.0, max=50.0),
        "rebalance": ParamSpec("enum", "monthly", "Rebalance cadence.",
                               choices=("weekly", "monthly")),
        "trend_ma_period": ParamSpec("integer", 0, "Extra gate: a held name must also close above "
                              "SMA(this) (0 disables).", min=0, max=400, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(lookback=252, skip_recent=21, top_n=2, abs_min_return=2.0,
                               rebalance="monthly", trend_ma_period=200, product="CNC",
                               sizing_method="fixed_capital", max_position_size_pct=40.0),
        "balanced": preset(lookback=252, skip_recent=0, top_n=3, abs_min_return=0.0,
                           rebalance="monthly", trend_ma_period=0, product="CNC",
                           sizing_method="fixed_capital", max_position_size_pct=30.0),
        "aggressive": preset(lookback=126, skip_recent=0, top_n=5, abs_min_return=-5.0,
                             rebalance="weekly", trend_ma_period=0, product="MIS",
                             sizing_method="fixed_capital", max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Monthly: hold the top_n names of the basket by trailing return, but only "
                     "those with a positive (>= abs_min_return) trailing return; the rest go to cash."),
        logic=("At each rebalance (uses data through the prior bar), for every name compute the "
               "trailing return over lookback bars, optionally skipping the last skip_recent bars. "
               "Rank descending; take the top_n. Keep only those whose trailing return > "
               "abs_min_return (and, if trend_ma_period > 0, close > SMA(trend_ma_period)). Target equal weight "
               "across the survivors; close everything else."),
        timeframe="day (weekly / monthly rebalance)",
        market_types=["NSE equity baskets", "sector-index ETFs"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Positional",
        risks=["Turns defensive only after a drawdown has already begun.",
               "Concentrated at small top_n; a single name can dominate the book.",
               "One-year warm-up; needs a real multi-name basket to work as designed."],
        best_for="A diversified positional book that should step aside in bear phases.",
        warning="Absolute momentum reduces but does not remove trend-reversal risk.",
        required_data=["Daily OHLCV for every name in the basket, at least lookback + a few bars"],
        example=("Basket of 8 large-caps, monthly, top 3: each month-start hold the 3 with the "
                 "highest 1-year return, dropping any whose 1-year return is negative to cash. "
                 "Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._last_seen: date | None = None
        self._last_rebalanced: date | None = None

    def on_bar(self, bar: Bar) -> None:
        d = self.bar_dt(bar).date()
        if self._last_seen is not None and d != self._last_seen and self._due(d):
            self._rebalance()
            self._last_rebalanced = self._last_seen
        self._last_seen = d
        self.ingest(bar)

    def _due(self, today: date) -> bool:
        if self._last_rebalanced is None:
            return True
        last = self._last_rebalanced
        if self.p["rebalance"] == "weekly":
            return today.isocalendar()[:2] != last.isocalendar()[:2]
        return (today.year, today.month) != (last.year, last.month)

    def _trailing_return(self, sym: str) -> float | None:
        buf = self._buffers.get(sym)
        if buf is None:
            return None
        closes = list(buf.closes)
        lb, skip = int(self.p["lookback"]), int(self.p["skip_recent"])
        if len(closes) < lb + 2:
            return None
        end = closes[-1 - skip] if skip else closes[-1]
        start = closes[-1 - lb]
        if start <= 0:
            return None
        return (end / start - 1.0) * 100.0

    def _above_ma(self, sym: str) -> bool:
        tm = int(self.p["trend_ma_period"])
        if tm <= 0:
            return True
        from app.strategies.indicators import sma

        buf = self._buffers.get(sym)
        if buf is None:
            return False
        closes = list(buf.closes)
        m = sma(closes, tm)
        return m is not None and closes[-1] > m

    def _rebalance(self) -> None:
        scored = [
            (sym, r) for sym in self._buffers
            if (r := self._trailing_return(sym)) is not None
        ]
        if not scored:
            return
        scored.sort(key=lambda kv: kv[1], reverse=True)
        top = scored[: int(self.p["top_n"])]
        keep = {
            sym for sym, r in top
            if r > float(self.p["abs_min_return"]) and self._above_ma(sym)
        }
        n = max(len(keep), 1)
        for sym, buf in self._buffers.items():
            price = buf.closes[-1] if buf.closes else 0.0
            if sym in keep and price > 0 and self.long_entries_allowed():
                slot = float(self.p["capital_allocation"]) / n
                qty = int(slot // price)
                self.rebalance_to(sym, max(qty, 0), exchange=self.p["exchange"],
                                  product=self.p["product"])
            else:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])

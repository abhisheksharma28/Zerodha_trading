"""Sector Momentum Rotation — hold the strongest NSE sectors, rotate monthly.

Relative-strength rotation applied to sector aggregates instead of single
stocks (Faber's "Relative Strength Strategies for Investing"; the GEM /
sector-ETF rotation literature). Each rebalance, rank the sector basket by
trailing return and hold the top ``hold_n`` equal-weight, keeping only
sectors whose own trailing return is positive (and, optionally, above a long
moving average) so the book moves to cash in a broad decline.

Not guaranteed profitable. Monthly rotation whipsaws around turning points
and a small ``hold_n`` concentrates the book. Validate out-of-sample with
turnover costs.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class SectorMomentumRotationStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "sector-momentum-rotation"
    NAME: ClassVar[str] = "Sector Momentum Rotation"
    CATEGORY: ClassVar[str] = "Rotation"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 260

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "mom_lookback": ParamSpec("integer", 126, "Trailing-return window (bars). ~126 = six months.",
                                  min=20, max=500),
        "skip_recent": ParamSpec("integer", 21, "Skip the most recent N bars of the lookback "
                                 "(short-term reversal control).", min=0, max=60),
        "hold_n": ParamSpec("integer", 3, "How many top sectors to hold equal-weight.",
                            min=1, max=15),
        "rebalance": ParamSpec("enum", "monthly", "Rebalance cadence.",
                               choices=("weekly", "monthly")),
        "abs_min_return": ParamSpec("number", 0.0, "A held sector's trailing return must exceed "
                                    "this % (absolute-momentum gate).", min=-50.0, max=50.0),
        "trend_ma_period": ParamSpec("integer", 200, "Also require the sector close > SMA(this) "
                              "(0 disables).", min=0, max=400, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "NRML", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(mom_lookback=252, skip_recent=21, hold_n=2, rebalance="monthly",
                               abs_min_return=2.0, trend_ma_period=200, product="NRML",
                               sizing_method="fixed_capital", max_position_size_pct=45.0),
        "balanced": preset(mom_lookback=126, skip_recent=21, hold_n=3, rebalance="monthly",
                           abs_min_return=0.0, trend_ma_period=200, product="NRML",
                           sizing_method="fixed_capital", max_position_size_pct=35.0),
        "aggressive": preset(mom_lookback=63, skip_recent=5, hold_n=4, rebalance="weekly",
                             abs_min_return=-5.0, trend_ma_period=0, product="NRML",
                             sizing_method="fixed_capital", max_position_size_pct=30.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Monthly: hold the hold_n NSE sector indices with the highest trailing "
                     "return, keeping only those with a positive (>= abs_min_return) trailing "
                     "return; the rest of the slot goes to cash."),
        logic=("At each rebalance (data through the prior bar), for every sector index compute "
               "the trailing return over mom_lookback bars, skipping the last skip_recent. Rank "
               "descending, take the top hold_n. Keep only sectors whose trailing return > "
               "abs_min_return and (if trend_ma_period > 0) whose close > SMA(trend_ma_period). "
               "Target equal weight across the survivors; close the rest."),
        timeframe="day (weekly / monthly rebalance)",
        market_types=["NSE sector indices (treated as sector-ETF proxies)"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Positional",
        risks=["Turns defensive only after a drawdown is already under way.",
               "Concentrated at small hold_n; one sector can dominate the book.",
               "Sector indices are not directly tradable — real execution needs sector ETFs "
               "or basket replication, with tracking error and cost."],
        best_for="A positional sleeve that leans into sector leadership and de-risks in a "
                 "broad downturn.",
        warning="Absolute momentum reduces but does not remove trend-reversal risk.",
        required_data=["Daily closes for each sector index, at least mom_lookback + a margin"],
        example=("11 NSE sector indices, monthly, hold_n=3: each month-start hold the 3 with "
                 "the highest 6-month return (skipping the last month), dropping any with a "
                 "negative 6-month return to cash. Mechanics only, not advice."),
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
        lb, skip = int(self.p["mom_lookback"]), int(self.p["skip_recent"])
        if len(closes) < lb + skip + 2:
            return None
        end = closes[-1 - skip] if skip else closes[-1]
        start = closes[-1 - lb - skip]
        if start <= 0:
            return None
        return (end / start - 1.0) * 100.0

    def _above_ma(self, sym: str) -> bool:
        tm = int(self.p["trend_ma_period"])
        if tm <= 0:
            return True
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
        top = scored[: int(self.p["hold_n"])]
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

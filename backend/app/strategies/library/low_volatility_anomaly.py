"""Low-Volatility Anomaly — hold the calmest names, rebalance periodically.

Decades of cross-sectional studies (Haugen & Baker; Baker, Bradley &
Wurgler; Blitz & van Vliet) find that low-volatility stocks have delivered
*higher* risk-adjusted returns than high-volatility stocks — the opposite of
what CAPM predicts. This template ranks the basket by trailing realised
volatility each rebalance and holds the ``hold_n`` lowest equal-weight, with
an optional trend filter so it steps aside from calm names that are quietly
bleeding.

Not guaranteed profitable. The premium is thin, slow, and can invert for
years (e.g. a sharp low-rate melt-up). Validate out-of-sample with turnover
costs.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import rolling_volatility, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class LowVolatilityAnomalyStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "low-volatility-anomaly"
    NAME: ClassVar[str] = "Low-Volatility Anomaly"
    CATEGORY: ClassVar[str] = "Factor / Anomaly"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int | None] = 60
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 260

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "vol_lookback": ParamSpec("integer", 120, "Trailing window (bars) for realised volatility.",
                                  min=20, max=500),
        "hold_n": ParamSpec("integer", 15, "How many lowest-volatility names to hold equal-weight.",
                            min=1, max=50),
        "rebalance": ParamSpec("enum", "monthly", "Rebalance cadence.",
                               choices=("weekly", "monthly")),
        "trend_ma_period": ParamSpec("integer", 0, "Optional: only hold a name while its close is "
                              "above SMA(this) (0 disables).", min=0, max=400, group="filter"),
        "max_names_ratio": ParamSpec("number", 1.0, "Cap hold_n at this fraction of the available "
                                     "names (keeps a tiny universe from over-concentrating).",
                                     min=0.1, max=1.0, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(vol_lookback=180, hold_n=20, rebalance="monthly",
                               trend_ma_period=200, product="CNC",
                               sizing_method="fixed_capital", max_position_size_pct=10.0),
        "balanced": preset(vol_lookback=120, hold_n=15, rebalance="monthly",
                           trend_ma_period=0, product="CNC",
                           sizing_method="fixed_capital", max_position_size_pct=12.0),
        "aggressive": preset(vol_lookback=90, hold_n=10, rebalance="weekly",
                             trend_ma_period=0, product="MIS",
                             sizing_method="fixed_capital", max_position_size_pct=15.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Each rebalance, hold the hold_n names with the lowest trailing realised "
                     "volatility equal-weight; optionally skip any below a long moving average."),
        logic=("At each rebalance (weekly or monthly, using data through the prior bar) compute "
               "annualised realised volatility over vol_lookback bars for every name. Rank "
               "ascending and take the hold_n lowest (capped at max_names_ratio of the available "
               "names). If trend_ma_period > 0, drop any whose close is below SMA(trend_ma_period). "
               "Target equal weight across the survivors; close everything else."),
        timeframe="day (weekly / monthly rebalance)",
        market_types=["NSE cash-equity baskets", "low-vol / min-vol style sleeves"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Positional",
        risks=["The premium is small and can reverse for multi-year stretches.",
               "Low-vol names cluster in a few defensive sectors — hidden concentration.",
               "In a liquidity-driven melt-up the high-vol names run away from it."],
        best_for="A defensive, low-turnover core sleeve.",
        warning="Low volatility is not low risk; a calm name can still trend down.",
        required_data=["Daily OHLCV for every name in the basket, at least vol_lookback + a margin"],
        example=("Basket of 200 liquid names, monthly, hold_n=15: each month-start hold the 15 "
                 "with the lowest 6-month realised volatility, equal-weight. Mechanics only, "
                 "not advice."),
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

    def _vol(self, sym: str) -> float | None:
        buf = self._buffers.get(sym)
        if buf is None:
            return None
        closes = list(buf.closes)
        lb = int(self.p["vol_lookback"])
        if len(closes) < lb + 2:
            return None
        return rolling_volatility(closes, lb)

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
            (sym, v) for sym in self._buffers
            if (v := self._vol(sym)) is not None and v > 0
        ]
        if not scored:
            return
        scored.sort(key=lambda kv: kv[1])
        cap = max(1, int(len(scored) * float(self.p["max_names_ratio"])))
        want = min(int(self.p["hold_n"]), cap)
        keep = {sym for sym, _v in scored[:want] if self._above_ma(sym)}
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

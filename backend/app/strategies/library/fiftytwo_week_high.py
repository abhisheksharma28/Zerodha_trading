"""52-Week-High Momentum — hold names trading near their trailing high.

Research (George & Hwang, 2004) found that a stock's nearness to its
trailing 52-week high predicts future returns better than raw past return:
stocks close to their high keep outperforming. This template goes long
while price sits within ``band_pct`` of its trailing ``high_window``-bar high
and momentum is positive; it exits when price falls a set distance below
that high.

Not guaranteed profitable. Buying strength near highs means sharp
reversals when the trend breaks. Validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import roc, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    entry: float
    trail_high: float


class FiftyTwoWeekHighStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "fiftytwo-week-high"
    NAME: ClassVar[str] = "52-Week-High Momentum"
    CATEGORY: ClassVar[str] = "Momentum"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 260

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "high_window": ParamSpec("integer", 252, "Trailing-high window (bars). ~252 = one year.",
                               min=40, max=750),
        "band_pct": ParamSpec("number", 3.0, "Enter while price is within this % of the trailing high.",
                              min=0.1, max=25.0),
        "exit_pct": ParamSpec("number", 12.0, "Exit when price is this % below the trailing high.",
                              min=1.0, max=50.0),
        "mom_lookback": ParamSpec("integer", 126, "Momentum lookback (bars) that must be positive.",
                                  min=5, max=500, group="filter"),
        "trend_ma": ParamSpec("integer", 200, "Also require close > SMA(this) (0 disables).",
                              min=0, max=250, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(high_window=252, band_pct=2.0, exit_pct=10.0, mom_lookback=252,
                               trend_ma=200, product="CNC", sizing_method="fixed_capital",
                               max_position_size_pct=20.0),
        "balanced": preset(high_window=252, band_pct=3.0, exit_pct=12.0, mom_lookback=126,
                           trend_ma=200, product="CNC", sizing_method="fixed_capital",
                           max_position_size_pct=25.0),
        "aggressive": preset(high_window=126, band_pct=5.0, exit_pct=15.0, mom_lookback=63,
                             trend_ma=0, product="MIS", sizing_method="fixed_capital",
                             max_position_size_pct=30.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Long while price is within band_pct of its trailing high with positive "
                     "momentum; exits exit_pct below that high."),
        logic=("trailing_high = max(high) over high_window. Enter long when close >= trailing_high x "
               "(1 - band_pct/100), ROC(mom_lookback) > 0, and (trend_ma == 0 or close > "
               "SMA(trend_ma)). Track the trailing high while in the trade and exit when close <= "
               "trailing_high x (1 - exit_pct/100)."),
        timeframe="day",
        market_types=["NSE cash equities"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Position",
        risks=["Buying near highs -> deep, fast drawdowns when the leadership rotates.",
               "Single-name version has no diversification; run it over a basket.",
               "One-year warm-up means little signal in a short backtest window."],
        best_for="Persistent leaders in a broad uptrend.",
        warning="Momentum near highs is fragile at turning points; respect the exit.",
        required_data=["OHLCV bars per instrument, at least high_window + mom_lookback bars"],
        example="On daily TITAN: price is 1.5% off its 252-day high, 6-month ROC positive, above "
                "the 200-SMA -> long; a slide to 12% below the running high -> exit.",
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._open: dict[str, _Open] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        highs, closes = list(buf.highs), list(buf.closes)
        hb = int(self.p["high_window"])
        if len(closes) < hb + 2:
            return
        trailing_high = max(highs[-hb:])
        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            pos.trail_high = max(pos.trail_high, trailing_high, bar.high)
            if price <= pos.trail_high * (1 - float(self.p["exit_pct"]) / 100.0):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if price < trailing_high * (1 - float(self.p["band_pct"]) / 100.0):
            return
        mom = roc(closes, int(self.p["mom_lookback"]))
        if mom is None or mom <= 0 or not self.long_entries_allowed():
            return
        tm = int(self.p["trend_ma"])
        if tm > 0:
            m = sma(closes, tm)
            if m is None or price <= m:
                return
        qty = self.size_position(price, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(entry=price, trail_high=trailing_high)

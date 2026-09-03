"""Relative-Strength Line New High — buy the market leaders.

The IBD / Minervini "relative strength line" is simply price divided by a
benchmark index. When that ratio makes a new high the stock is
outperforming the market; leaders that are *also* trading near their own
price high have historically continued to lead. This template goes long on
that double confirmation and exits when relative strength rolls over.

Not guaranteed profitable. Leadership rotates fast and reversals from highs
are sharp; the RS-line stop and a price stop carry the risk. Validate
out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    entry: float
    stop: float
    rs_high: float
    entry_index: int


class RsLineHighStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "rs-line-high"
    NAME: ClassVar[str] = "Relative-Strength Line New High"
    CATEGORY: ClassVar[str] = "Momentum"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int | None] = 80
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 260

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "benchmark": ParamSpec("string", "NIFTY 50", "Index symbol the RS line is measured "
                               "against (must be one of the fed instruments)."),
        "rs_lookback": ParamSpec("integer", 126, "Window over which the RS line must make a new "
                                 "high.", min=20, max=500),
        "price_high_window": ParamSpec("integer", 126, "Window for the stock's own trailing-high "
                              "check.", min=20, max=500),
        "price_band_pct": ParamSpec("number", 8.0, "Enter only while price is within this % of its "
                                    "own trailing high.", min=0.5, max=30.0),
        "rs_exit_pct": ParamSpec("number", 6.0, "Exit when the RS line falls this % below its "
                                 "running high since entry.", min=1.0, max=30.0, group="risk"),
        "trend_ma_period": ParamSpec("integer", 200, "Also require close > SMA(this) (0 disables).",
                              min=0, max=400, group="filter"),
        "atr_period": ParamSpec("integer", 14, "ATR window for the hard stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 3.0, "Hard stop distance in ATRs.", min=0.5, max=10.0,
                                   group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 disables).",
                                      min=0, max=500, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(rs_lookback=189, price_high_window=189, price_band_pct=5.0,
                               rs_exit_pct=5.0, trend_ma_period=200, atr_stop_mult=3.5,
                               product="CNC", sizing_method="fixed_capital",
                               max_position_size_pct=15.0),
        "balanced": preset(rs_lookback=126, price_high_window=126, price_band_pct=8.0,
                           rs_exit_pct=6.0, trend_ma_period=200, atr_stop_mult=3.0,
                           product="CNC", sizing_method="fixed_capital",
                           max_position_size_pct=20.0),
        "aggressive": preset(rs_lookback=63, price_high_window=63, price_band_pct=12.0,
                             rs_exit_pct=8.0, trend_ma_period=0, atr_stop_mult=2.5,
                             product="MIS", sizing_method="fixed_capital",
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Goes long a name when its relative-strength line (price / benchmark) makes a "
                     "new rs_lookback high while price is within price_band_pct of its own "
                     "trailing high; exits when relative strength rolls over."),
        logic=("RS = close / benchmark_close, using bars where both legs printed. Enter long when "
               "RS >= max(RS) over rs_lookback, close >= trailing_high(price_high_window) x "
               "(1 - price_band_pct/100), and (trend_ma_period == 0 or close > "
               "SMA(trend_ma_period)). Track the RS high while in the trade; exit when RS falls "
               "rs_exit_pct below it, the ATR stop is hit, or max_holding_bars elapse."),
        timeframe="day",
        market_types=["NSE cash equities measured against a broad index"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Positional",
        risks=["Buying strength near highs -> fast, deep reversals when leadership rotates.",
               "RS line can new-high on a falling market if the stock falls less — pair it with "
               "the trend filter.",
               "Single-name signal; run it across a basket for diversification."],
        best_for="Identifying and holding the genuine leaders in an up market.",
        warning="Relative strength is relative — a leader can still be in an absolute downtrend.",
        required_data=["Daily OHLCV for each stock and the benchmark index over the same window"],
        example=("On daily DIXON vs NIFTY 50: the RS line prints a fresh 6-month high while DIXON "
                 "is 3% off its own high and above the 200-SMA -> long; exit when RS slips 6% off "
                 "its peak. Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._open: dict[str, _Open] = {}
        self._seen: dict[str, int] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        bench = str(self.p["benchmark"])
        if sym == bench:
            return
        bbuf = self._buffers.get(bench)
        if bbuf is None or not bbuf.closes:
            return

        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        closes = list(buf.closes)
        bcloses = list(bbuf.closes)
        rl = int(self.p["rs_lookback"])
        pw = int(self.p["price_high_window"])
        need = max(rl, pw, int(self.p["trend_ma_period"])) + 2
        m = min(len(closes), len(bcloses))
        if m < need:
            return

        # align the two series on their shared tail (fill-at-close: same length ⇒ same days)
        a_close = closes[-m:]
        b_close = bcloses[-m:]
        rs = [a_close[i] / b_close[i] for i in range(m) if b_close[i] > 0]
        if len(rs) < need:
            return
        price = a_close[-1]
        pos = self._open.get(sym)

        if pos is not None:
            pos.rs_high = max(pos.rs_high, rs[-1])
            hold = int(self.p["max_holding_bars"])
            drop = pos.rs_high * (1 - float(self.p["rs_exit_pct"]) / 100.0)
            if (rs[-1] <= drop or bar.low <= pos.stop
                    or (hold > 0 and idx - pos.entry_index >= hold)):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if rs[-1] < max(rs[-rl:]):
            return
        trailing_high = max(a_close[-pw:])
        if price < trailing_high * (1 - float(self.p["price_band_pct"]) / 100.0):
            return
        tm = int(self.p["trend_ma_period"])
        if tm > 0:
            ma = sma(a_close, tm)
            if ma is None or price <= ma:
                return
        if not self.long_entries_allowed():
            return
        a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        if a is None or a <= 0:
            return
        risk = float(self.p["atr_stop_mult"]) * a
        qty = self.size_position(price, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(entry=price, stop=price - risk, rs_high=rs[-1], entry_index=idx)

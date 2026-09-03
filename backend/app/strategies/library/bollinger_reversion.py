"""Bollinger Band Mean Reversion — fade the lower band, cover at the mean.

Buy when price closes below the lower Bollinger band (a stretched move) and
the longer trend is still up; scale out / exit as price reverts to the
middle band. The band width adapts to volatility, so entries self-calibrate
to the regime.

Not guaranteed profitable. In a genuine breakdown price rides the lower
band for weeks; the regime filter and a hard stop are the protection.
Validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, bollinger, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    entry: float
    stop: float
    entry_index: int


class BollingerReversionStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "bollinger-reversion"
    NAME: ClassVar[str] = "Bollinger Band Mean Reversion"
    CATEGORY: ClassVar[str] = "Mean Reversion"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "bb_period": ParamSpec("integer", 20, "Bollinger moving-average / stdev window.", min=5, max=100),
        "bb_stdev": ParamSpec("number", 2.0, "Band width in standard deviations.", min=0.5, max=4.0),
        "entry_pctb": ParamSpec("number", 0.0, "Buy when %B <= this (0 = at/below the lower band).",
                                min=-1.0, max=0.5),
        "exit_pctb": ParamSpec("number", 0.5, "Exit when %B >= this (0.5 = the middle band).",
                               min=0.0, max=1.2),
        "regime_window": ParamSpec("integer", 100, "Only buy while close > SMA(this) (0 disables).",
                               min=0, max=400, group="filter"),
        "max_holding_bars": ParamSpec("integer", 15, "Force exit after N bars (0 disables).",
                                      min=0, max=200, group="risk"),
        "atr_period": ParamSpec("integer", 14, "ATR period for the hard stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 2.5, "Hard stop distance in ATRs.", min=0.5, max=10.0,
                                   group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(bb_period=20, bb_stdev=2.5, entry_pctb=-0.1, exit_pctb=0.5,
                               regime_window=200, max_holding_bars=12, atr_stop_mult=3.0, product="CNC",
                               sizing_method="fixed_capital", max_position_size_pct=20.0),
        "balanced": preset(bb_period=20, bb_stdev=2.0, entry_pctb=0.0, exit_pctb=0.5,
                           regime_window=100, max_holding_bars=15, atr_stop_mult=2.5, product="CNC",
                           sizing_method="fixed_capital", max_position_size_pct=25.0),
        "aggressive": preset(bb_period=14, bb_stdev=1.8, entry_pctb=0.1, exit_pctb=0.6,
                             regime_window=0, max_holding_bars=8, atr_stop_mult=2.0, product="MIS",
                             sizing_method="fixed_capital", max_position_size_pct=30.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Buys a stretched move below the lower Bollinger band while the longer trend "
                     "is up; exits back at the middle band, on a time stop, or a hard ATR stop."),
        logic=("%B = (close - lower) / (upper - lower) from Bollinger(bb_period, bb_stdev). Enter "
               "long when %B <= entry_pctb and (regime_window == 0 or close > SMA(regime_window)). Exit "
               "when %B >= exit_pctb OR max_holding_bars elapsed OR the ATR stop is hit."),
        timeframe="day / 60m / 15m",
        market_types=["NSE cash equities", "index ETFs"],
        supports_long=True, supports_short=False, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Short swing",
        risks=["Price can walk down the lower band in a real breakdown.",
               "Frequent entries in high-vol regimes if the regime filter is off.",
               "Well-known pattern; edge may be thin after costs."],
        best_for="Range-bound or gently trending liquid names.",
        warning="A counter-trend entry; the stop and the regime filter carry the risk.",
        required_data=["OHLCV bars per instrument, at least max(bb_period, regime_window) + a few bars"],
        example="On daily RELIANCE above its 100-SMA: close prints below the lower 20,2 band -> buy; "
                "%B recovers to 0.5 -> exit.",
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._open: dict[str, _Open] = {}
        self._seen: dict[str, int] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        closes = list(buf.closes)
        need = max(int(self.p["bb_period"]), int(self.p["regime_window"])) + 2
        if len(closes) < need:
            return
        bb = bollinger(closes, int(self.p["bb_period"]), float(self.p["bb_stdev"]))
        a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        if bb is None or a is None:
            return
        low_b, _mid, up_b = bb
        rng = up_b - low_b
        if rng <= 0:
            return
        price = closes[-1]
        pctb = (price - low_b) / rng
        pos = self._open.get(sym)

        if pos is not None:
            hold = int(self.p["max_holding_bars"])
            if (pctb >= float(self.p["exit_pctb"]) or bar.low <= pos.stop
                    or (hold > 0 and idx - pos.entry_index >= hold)):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        rm = int(self.p["regime_window"])
        if rm > 0:
            m = sma(closes, rm)
            if m is None or price <= m:
                return
        if pctb > float(self.p["entry_pctb"]) or not self.long_entries_allowed():
            return
        risk = float(self.p["atr_stop_mult"]) * a
        qty = self.size_position(price, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(entry=price, stop=price - risk, entry_index=idx)

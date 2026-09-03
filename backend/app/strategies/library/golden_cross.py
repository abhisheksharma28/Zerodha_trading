"""Golden Cross — the 50/200 moving-average regime.

Long while the fast MA is above the slow MA (a "golden cross"), flat (or
short) while it is below (a "death cross"). The oldest, most-cited trend
filter there is; slow, low-turnover, and a useful baseline every other
strategy should be measured against.

Not guaranteed profitable. It is late into every trend and out late too,
and it chops in range-bound years. Validate out-of-sample.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, ema, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class GoldenCrossStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "golden-cross"
    NAME: ClassVar[str] = "Golden Cross (50/200)"
    CATEGORY: ClassVar[str] = "Trend Following"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m")
    MIN_BARS_REQUIRED: ClassVar[int] = 210

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "fast_period": ParamSpec("integer", 50, "Fast moving average.", min=3, max=200),
        "slow_period": ParamSpec("integer", 200, "Slow moving average.", min=10, max=400),
        "ma_type": ParamSpec("enum", "sma", "Moving-average type.", choices=("sma", "ema")),
        "allow_short": ParamSpec("boolean", False, "Go short on a death cross instead of flat."),
        "atr_period": ParamSpec("integer", 14, "ATR period for a protective stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 0.0, "Hard stop in ATRs (0 = only exit on the cross).",
                                   min=0.0, max=20.0, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(fast_period=50, slow_period=200, ma_type="sma", allow_short=False,
                               atr_stop_mult=0.0, product="CNC", sizing_method="fixed_capital",
                               max_position_size_pct=25.0),
        "balanced": preset(fast_period=50, slow_period=150, ma_type="ema", allow_short=False,
                           atr_stop_mult=0.0, product="CNC", sizing_method="fixed_capital",
                           max_position_size_pct=30.0),
        "aggressive": preset(fast_period=20, slow_period=100, ma_type="ema", allow_short=True,
                             atr_stop_mult=3.0, product="MIS", sizing_method="fixed_capital",
                             max_position_size_pct=35.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description="Long while MA(fast) > MA(slow); flat (or short) while below. A slow regime filter.",
        logic=("Each bar compute MA(fast) and MA(slow) of close (sma or ema). Target a full long "
               "position while fast > slow; go flat on the down-cross, or short if allow_short. "
               "Optional hard stop at atr_stop_mult x ATR from entry."),
        timeframe="day / 60m",
        market_types=["NSE equities", "index funds / ETFs"],
        supports_long=True, supports_short=True, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Position",
        risks=["Enters and exits well after the turn — large give-back around tops.",
               "Repeated small losses when the two MAs hug each other in a range.",
               "200-bar warm-up means no signal early in a short backtest."],
        best_for="A low-effort trend/regime filter and a benchmark for fancier strategies.",
        warning="Simple and slow by design; it will lag every major move.",
        required_data=["OHLCV bars per instrument, at least slow + a few bars"],
        example="On daily INFY: EMA50 crosses above EMA150 -> hold long; crosses below -> go flat.",
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._entry: dict[str, tuple[int, float, float]] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        closes = list(buf.closes)
        f, s = int(self.p["fast_period"]), int(self.p["slow_period"])
        if len(closes) < s + 2:
            return
        ma = ema if self.p["ma_type"] == "ema" else sma
        fast_now, slow_now = ma(closes, f), ma(closes, s)
        fast_prev, slow_prev = ma(closes[:-1], f), ma(closes[:-1], s)
        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return
        up = fast_now > slow_now  # type: ignore[operator]
        held = self._entry.get(sym)

        if held is not None:
            side, epx, eatr = held
            stop_hit = eatr > 0 and (
                (side == 1 and bar.low <= epx - eatr) or (side == -1 and bar.high >= epx + eatr)
            )
            want_side = 1 if up else (-1 if self.p["allow_short"] else 0)
            if want_side != side or stop_hit:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._entry.pop(sym, None)
                held = None

        if held is None:
            side = 1 if up else (-1 if self.p["allow_short"] else 0)
            if side == 0:
                return
            if side == 1 and not self.long_entries_allowed():
                return
            a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"])) or 0.0
            risk = float(self.p["atr_stop_mult"]) * a
            qty = self.size_position(bar.close, stop_distance=risk or None, symbol=sym)
            if qty <= 0:
                return
            self.submit(sym, "BUY" if side == 1 else "SELL", qty,
                        exchange=self.p["exchange"], product=self.p["product"])
            self._entry[sym] = (side, float(bar.close), risk)

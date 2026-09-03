"""Supertrend — an ATR-band trend follower.

The Supertrend line sits ``multiplier x ATR`` below price in an uptrend and
the same distance above price in a downtrend; it flips when price closes
through it. Go long on an up-flip, exit (or reverse) on a down-flip. One of
the most widely used trend tools on Indian retail platforms; simple, fully
mechanical, and its stop is built in (the line itself).

Not guaranteed profitable. Like every trend follower it bleeds in choppy,
sideways markets and gives back a chunk of each move on the exit. Validate
out-of-sample with realistic costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _St:
    upper: float
    lower: float
    dir: int  # +1 up, -1 down


class SupertrendStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "supertrend"
    NAME: ClassVar[str] = "Supertrend"
    CATEGORY: ClassVar[str] = "Trend Following"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "30m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 40

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "atr_period": ParamSpec("integer", 10, "ATR lookback for the band width.", min=2, max=100),
        "multiplier": ParamSpec("number", 3.0, "Band = multiplier x ATR from the mid price.",
                                min=0.5, max=10.0),
        "allow_short": ParamSpec("boolean", False, "Also take the short side on a down-flip."),
        "confirm_bars": ParamSpec("integer", 1, "Consecutive closes beyond the line before a flip "
                                  "is accepted.", min=1, max=5, group="filter"),
        "trend_ma_period": ParamSpec("integer", 0, "If > 0, only take longs while close > SMA(this) "
                              "(0 disables the regime filter).", min=0, max=400, group="filter"),
        "take_profit_atr": ParamSpec("number", 0.0, "Take profit at this many ATRs from entry "
                                     "(0 = ride the flip).", min=0.0, max=30.0, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(atr_period=14, multiplier=4.0, allow_short=False, confirm_bars=2,
                               trend_ma_period=200, take_profit_atr=0.0, product="CNC",
                               sizing_method="risk_per_trade", risk_per_trade_pct=0.5,
                               max_position_size_pct=15.0),
        "balanced": preset(atr_period=10, multiplier=3.0, allow_short=False, confirm_bars=1,
                           trend_ma_period=0, take_profit_atr=0.0, product="MIS",
                           sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
                           max_position_size_pct=20.0),
        "aggressive": preset(atr_period=7, multiplier=2.0, allow_short=True, confirm_bars=1,
                             trend_ma_period=0, take_profit_atr=0.0, product="MIS",
                             sizing_method="risk_per_trade", risk_per_trade_pct=1.5,
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Follows the Supertrend (ATR-band) line: long while it trails below price, "
                     "flat/short after it flips above. The line is the stop."),
        logic=("Each bar: ATR(atr_period); basic bands = (high+low)/2 +/- multiplier x ATR, then "
               "the usual Supertrend carry-forward so the final band only tightens with the trend. "
               "Direction flips to up when close holds above the down-band for confirm_bars, and "
               "vice versa. Enter long on an up-flip (optionally only if close > SMA(trend_ma_period)); "
               "exit on a down-flip, or reverse short if allow_short; optional take-profit at "
               "take_profit_atr ATRs."),
        timeframe="day / 60m / 30m / 15m",
        market_types=["NSE equities", "index & stock futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Swing / Intraday",
        risks=["Whipsaws badly in range-bound markets — many small losing flips.",
               "Gives back part of every trend on the lagging exit.",
               "A wide multiplier means a deep initial stop."],
        best_for="Trending, liquid instruments; a clean rules-based trailing stop.",
        warning="A pure trend follower; expect long losing streaks in sideways regimes.",
        required_data=["OHLCV bars per instrument, at least atr_period + a few bars"],
        example=("On daily NIFTY futures: ATR(10) x 3 band; price closes above the falling band -> "
                 "flip up, go long; a later close below the rising band -> flip down, exit. "
                 "Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._st: dict[str, _St] = {}
        self._entry: dict[str, tuple[int, float, float]] = {}  # side, entry px, atr
        self._streak: dict[str, int] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        highs, lows, closes = list(buf.highs), list(buf.lows), list(buf.closes)
        n = int(self.p["atr_period"])
        if len(closes) < n + 2:
            return
        a = atr(highs, lows, closes, n)
        if not a:
            return
        mid = (bar.high + bar.low) / 2.0
        mult = float(self.p["multiplier"])
        up_basic, dn_basic = mid + mult * a, mid - mult * a
        prev = self._st.get(sym)
        if prev is None:
            self._st[sym] = _St(up_basic, dn_basic, 1 if bar.close >= mid else -1)
            return
        # carry-forward: the band only moves in the trend's favour
        upper = up_basic if (up_basic < prev.upper or closes[-2] > prev.upper) else prev.upper
        lower = dn_basic if (dn_basic > prev.lower or closes[-2] < prev.lower) else prev.lower
        direction = prev.dir
        need = int(self.p["confirm_bars"])
        against = self._streak.get(sym, 0)
        breach = (prev.dir == 1 and bar.close < lower) or (prev.dir == -1 and bar.close > upper)
        against = against + 1 if breach else 0
        if against >= need:
            direction = -prev.dir
            against = 0
        self._streak[sym] = against
        self._st[sym] = _St(upper, lower, direction)

        flipped = direction != prev.dir
        held = self._entry.get(sym)
        tp = float(self.p["take_profit_atr"])
        if held is not None:
            side, epx, eatr = held
            hit_tp = tp > 0 and (
                (side == 1 and bar.high >= epx + tp * eatr)
                or (side == -1 and bar.low <= epx - tp * eatr)
            )
            if flipped or hit_tp:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._entry.pop(sym, None)
                held = None

        if held is None and flipped:
            tm = int(self.p["trend_ma_period"])
            if direction == 1 and tm > 0:
                m = sma(closes, tm)
                if m is not None and bar.close < m:
                    return
            if direction == 1 and not self.long_entries_allowed():
                return
            if direction == -1 and not self.p["allow_short"]:
                return
            risk = mult * a
            qty = self.size_position(bar.close, stop_distance=risk, symbol=sym)
            if qty <= 0:
                return
            self.submit(sym, "BUY" if direction == 1 else "SELL", qty,
                        exchange=self.p["exchange"], product=self.p["product"])
            self._entry[sym] = (direction, float(bar.close), a)

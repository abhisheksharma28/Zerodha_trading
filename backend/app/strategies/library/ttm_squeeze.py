"""TTM Squeeze — trade the release of a volatility coil.

After John Carter's "Mastering the Trade": when the Bollinger Bands
contract entirely *inside* the Keltner Channels the market is coiling
("squeeze on"); the first bar the bands push back outside the channels the
squeeze "fires" and a directional move often follows. Enter in the
direction of a momentum oscillator on the fire bar; exit when momentum
rolls over, a fresh squeeze forms, or an ATR stop is hit.

Not guaranteed profitable. Plenty of squeezes fire into noise and reverse;
the momentum gate and the stop carry the risk. Validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, bollinger, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    side: int          # +1 long, -1 short
    entry: float
    stop: float
    entry_index: int


class TtmSqueezeStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "ttm-squeeze"
    NAME: ClassVar[str] = "TTM Squeeze"
    CATEGORY: ClassVar[str] = "Volatility Breakout"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 40
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "bb_period": ParamSpec("integer", 20, "Bollinger / Keltner basis window.", min=5, max=100),
        "bb_stdev": ParamSpec("number", 2.0, "Bollinger width in standard deviations.",
                              min=1.0, max=4.0),
        "kc_mult": ParamSpec("number", 1.5, "Keltner width in ATRs (Carter's default 1.5).",
                             min=0.5, max=4.0),
        "atr_period": ParamSpec("integer", 20, "ATR window for the Keltner channel and the stop.",
                                min=2, max=100),
        "mom_period": ParamSpec("integer", 20, "Momentum oscillator lookback (close - SMA).",
                                min=3, max=100),
        "mom_slope_bars": ParamSpec("integer", 3, "Bars over which momentum must be rising/falling "
                                    "to confirm direction.", min=1, max=20),
        "allow_short": ParamSpec("boolean", False, "Also take the short side when a squeeze fires "
                                 "down."),
        "atr_stop_mult": ParamSpec("number", 2.5, "Hard stop distance in ATRs.", min=0.5, max=10.0,
                                   group="risk"),
        "max_holding_bars": ParamSpec("integer", 25, "Force exit after N bars (0 disables).",
                                      min=0, max=250, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(bb_period=20, bb_stdev=2.0, kc_mult=2.0, atr_period=20,
                               mom_period=20, mom_slope_bars=4, allow_short=False,
                               atr_stop_mult=3.0, max_holding_bars=20, product="CNC",
                               sizing_method="risk_per_trade", risk_per_trade_pct=0.5,
                               max_position_size_pct=15.0),
        "balanced": preset(bb_period=20, bb_stdev=2.0, kc_mult=1.5, atr_period=20,
                           mom_period=20, mom_slope_bars=3, allow_short=False,
                           atr_stop_mult=2.5, max_holding_bars=25, product="MIS",
                           sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
                           max_position_size_pct=20.0),
        "aggressive": preset(bb_period=20, bb_stdev=2.0, kc_mult=1.0, atr_period=14,
                             mom_period=12, mom_slope_bars=2, allow_short=True,
                             atr_stop_mult=2.0, max_holding_bars=15, product="MIS",
                             sizing_method="risk_per_trade", risk_per_trade_pct=1.5,
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Waits for the Bollinger Bands to contract inside the Keltner Channels "
                     "(a volatility squeeze), then enters on the bar the squeeze releases, in "
                     "the direction of a momentum oscillator."),
        logic=("Squeeze is ON while BB(bb_period, bb_stdev) sits fully inside "
               "Keltner(bb_period basis, kc_mult x ATR(atr_period)). On the first bar it turns "
               "OFF after being ON, read momentum = close - SMA(mom_period): go long if momentum "
               "> 0 and rising over mom_slope_bars (short the mirror if allow_short). Exit when "
               "momentum crosses back through zero, a new squeeze forms, max_holding_bars "
               "elapse, or price hits entry -/+ atr_stop_mult x ATR."),
        timeframe="day / 60m / 15m",
        market_types=["NSE equities", "index & stock futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Swing / Intraday",
        risks=["A squeeze can fire and immediately reverse — false breakouts are common.",
               "The momentum oscillator lags; the first leg of the move may be missed.",
               "Back-to-back squeezes in a range grind out small losses."],
        best_for="Liquid names that alternate between tight consolidation and clean expansion.",
        warning="A squeeze marks *potential* energy, not direction; the momentum gate is essential.",
        required_data=["OHLCV bars per instrument, at least bb_period + atr_period + a margin"],
        example=("On daily RELIANCE: BB(20,2) slips inside the 1.5-ATR Keltner for two weeks, then "
                 "the upper band pops outside with momentum turning up -> long; exit when momentum "
                 "rolls back under zero. Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._sq_on: dict[str, bool] = {}
        self._open: dict[str, _Open] = {}
        self._seen: dict[str, int] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        closes = list(buf.closes)
        n = int(self.p["bb_period"])
        na = int(self.p["atr_period"])
        if len(closes) < max(n, na, int(self.p["mom_period"])) + 3:
            return

        bb = bollinger(closes, n, float(self.p["bb_stdev"]))
        a = atr(list(buf.highs), list(buf.lows), closes, na)
        basis = sma(closes, n)
        if bb is None or a is None or basis is None:
            return
        bb_lo, _mid, bb_hi = bb
        kc = float(self.p["kc_mult"]) * a
        kc_lo, kc_hi = basis - kc, basis + kc

        was_on = self._sq_on.get(sym, False)
        is_on = bb_lo > kc_lo and bb_hi < kc_hi
        self._sq_on[sym] = is_on
        fired = was_on and not is_on

        mom = closes[-1] - basis
        mom_prev = closes[-1 - int(self.p["mom_slope_bars"])] - (
            sma(closes[:-int(self.p["mom_slope_bars"])], n) or closes[-1]
        )
        rising = mom > mom_prev

        pos = self._open.get(sym)
        if pos is not None:
            hold = int(self.p["max_holding_bars"])
            stop_hit = (pos.side == 1 and bar.low <= pos.stop) or (
                pos.side == -1 and bar.high >= pos.stop)
            mom_flip = (pos.side == 1 and mom < 0) or (pos.side == -1 and mom > 0)
            if stop_hit or mom_flip or is_on or (hold > 0 and idx - pos.entry_index >= hold):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if not fired:
            return
        side = 0
        if mom > 0 and rising:
            side = 1
        elif mom < 0 and not rising and self.p["allow_short"]:
            side = -1
        if side == 1 and not self.long_entries_allowed():
            return
        if side == 0:
            return
        risk = float(self.p["atr_stop_mult"]) * a
        qty = self.size_position(closes[-1], stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == 1 else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(side=side, entry=float(closes[-1]),
                                stop=closes[-1] - side * risk, entry_index=idx)

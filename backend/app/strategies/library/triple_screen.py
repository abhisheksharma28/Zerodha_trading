"""Triple Screen — a three-filter trend-with-the-tide system.

After Dr Alexander Elder's "Trading for a Living": trade only in the
direction of the longer-term trend (screen 1), use a counter-trend
oscillator dip to time the entry (screen 2), and trigger on a break of the
prior bar's extreme (screen 3). A single-timeframe approximation of the
weekly/daily/intraday original: the "tide" is the slope of a long moving
average on the same series.

Not guaranteed profitable. A lagging tide filter still whipsaws in choppy
markets; validate out-of-sample with realistic costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, rsi, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Armed:
    side: str
    trigger: float
    stop: float
    armed_index: int


@dataclass
class _Open:
    side: str
    entry: float
    stop: float
    entry_index: int
    risk: float


class TripleScreenStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "triple-screen"
    NAME: ClassVar[str] = "Triple Screen"
    CATEGORY: ClassVar[str] = "Trend Following"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 25
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "tide_ma": ParamSpec("integer", 150, "Long MA whose slope is the 'tide' (screen 1).",
                             min=20, max=400),
        "tide_slope_bars": ParamSpec("integer", 5, "Bars over which the tide slope is measured.",
                                     min=1, max=40),
        "osc_period": ParamSpec("integer", 14, "RSI period for the entry-timing oscillator (screen 2).",
                                min=2, max=100),
        "osc_buy": ParamSpec("number", 40.0, "In an up-tide, wait for RSI <= this (the pullback).",
                             min=1.0, max=99.0),
        "osc_sell": ParamSpec("number", 60.0, "In a down-tide, wait for RSI >= this (the bounce).",
                              min=1.0, max=99.0),
        "arm_expiry_bars": ParamSpec("integer", 3, "Bars the screen-3 stop-entry trigger stays live.",
                                     min=1, max=20),
        "allow_short": ParamSpec("boolean", False, "Also trade the short side in a down-tide."),
        "atr_period": ParamSpec("integer", 14, "ATR period for the fallback stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 0.0, "If > 0, widen the stop to max(2-bar extreme, "
                                   "this x ATR).", min=0.0, max=10.0, group="risk"),
        "trailing_atr_mult": ParamSpec("number", 0.0, "Trailing stop in ATRs (0 disables).",
                                       min=0.0, max=10.0, group="risk"),
        "take_profit_r": ParamSpec("number", 0.0, "Take profit at this multiple of initial risk "
                                   "(0 disables).", min=0.0, max=20.0, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(tide_ma=200, tide_slope_bars=8, osc_buy=35.0, allow_short=False,
                               atr_stop_mult=1.5, trailing_atr_mult=3.0, take_profit_r=2.0,
                               product="CNC", sizing_method="risk_per_trade", risk_per_trade_pct=0.5,
                               max_position_size_pct=15.0),
        "balanced": preset(tide_ma=150, tide_slope_bars=5, osc_buy=40.0, osc_sell=60.0,
                           allow_short=False, atr_stop_mult=0.0, trailing_atr_mult=0.0,
                           take_profit_r=2.0, product="MIS", sizing_method="risk_per_trade",
                           risk_per_trade_pct=1.0, max_position_size_pct=20.0),
        "aggressive": preset(tide_ma=100, tide_slope_bars=3, osc_buy=45.0, osc_sell=55.0,
                             allow_short=True, arm_expiry_bars=2, atr_stop_mult=0.0,
                             trailing_atr_mult=2.5, take_profit_r=0.0, product="MIS",
                             sizing_method="risk_per_trade", risk_per_trade_pct=1.5,
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Trades with the slope of a long MA (the tide), uses an RSI pullback against "
                     "that tide to time the entry, and triggers on a break of the prior bar's "
                     "extreme; stop at the two-bar extreme."),
        logic=("Screen 1: tide = sign of SMA(tide_ma) now minus tide_slope_bars ago. Screen 2: in an "
               "up-tide wait for RSI(osc_period) <= osc_buy (a pullback); mirror for a down-tide. "
               "Screen 3: arm a stop-entry at the prior bar's high (long) / low (short) for "
               "arm_expiry_bars; on the break, enter with the stop at the two-bar low/high "
               "(optionally widened to atr_stop_mult x ATR). Exit on stop, optional ATR trailing "
               "stop, optional take-profit, or the tide flipping against the position."),
        timeframe="day / 60minute / 15minute",
        market_types=["NSE equities", "liquid futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Swing / Intraday",
        risks=["A lagging MA-slope tide keeps you long into the start of a downtrend.",
               "Range-bound markets give repeated pullback signals that fail at the trigger.",
               "Gaps through the two-bar stop cause larger-than-modelled losses."],
        best_for="Pullback entries inside an established trend.",
        warning="The tide filter lags; it will not get you out at the top.",
        required_data=["OHLCV bars per instrument, at least tide_ma + a few bars"],
        example=("On daily INFY bars: the 150-day SMA is rising (up-tide), RSI dips to 38 (pullback), "
                 "and the next bar takes out the prior high -> go long with the stop at the two-bar "
                 "low. Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._armed: dict[str, _Armed] = {}
        self._open: dict[str, _Open] = {}
        self._seen: dict[str, int] = {}

    def _tide(self, closes: list[float]) -> int:
        n, k = int(self.p["tide_ma"]), int(self.p["tide_slope_bars"])
        now = sma(closes, n)
        past = sma(closes[: len(closes) - k], n) if len(closes) > n + k else None
        if now is None or past is None:
            return 0
        return 1 if now > past else -1 if now < past else 0

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        closes = list(buf.closes)
        if len(closes) < int(self.p["tide_ma"]) + int(self.p["tide_slope_bars"]) + 2:
            return
        tide = self._tide(closes)
        r = rsi(closes, int(self.p["osc_period"]))
        a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        if r is None:
            return
        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            if self._should_exit(sym, pos, bar, tide, a):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
                self._armed.pop(sym, None)
            return

        armed = self._armed.get(sym)
        if armed is not None:
            if idx - armed.armed_index > int(self.p["arm_expiry_bars"]):
                self._armed.pop(sym, None)
            elif armed.side == "long" and bar.high >= armed.trigger:
                self._enter(sym, "long", max(price, armed.trigger), armed.stop, idx, a)
                return
            elif armed.side == "short" and bar.low <= armed.trigger:
                self._enter(sym, "short", min(price, armed.trigger), armed.stop, idx, a)
                return

        prev_hi, prev_lo = buf.bars[-2].high, buf.bars[-2].low
        two_lo = min(bar.low, prev_lo)
        two_hi = max(bar.high, prev_hi)
        if tide > 0 and r <= float(self.p["osc_buy"]) and self.long_entries_allowed():
            self._armed[sym] = _Armed("long", float(bar.high), float(two_lo), idx)
        elif tide < 0 and self.p["allow_short"] and r >= float(self.p["osc_sell"]):
            self._armed[sym] = _Armed("short", float(bar.low), float(two_hi), idx)

    def _enter(self, sym: str, side: str, entry: float, raw_stop: float, idx: int,
               a: float | None) -> None:
        risk = abs(entry - raw_stop)
        mult = float(self.p["atr_stop_mult"])
        if mult > 0 and a:
            risk = max(risk, mult * a)
        if risk <= 0:
            risk = entry * 0.01
        stop = entry - risk if side == "long" else entry + risk
        qty = self.size_position(entry, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(side=side, entry=entry, stop=stop, entry_index=idx, risk=risk)
        self._armed.pop(sym, None)

    def _should_exit(self, sym: str, pos: _Open, bar: Bar, tide: int, a: float | None) -> bool:
        trail = float(self.p["trailing_atr_mult"])
        price = float(bar.close)
        if trail > 0 and a:
            if pos.side == "long":
                pos.stop = max(pos.stop, price - trail * a)
            else:
                pos.stop = min(pos.stop, price + trail * a)
        tp = float(self.p["take_profit_r"])
        if pos.side == "long":
            if bar.low <= pos.stop or tide < 0:
                return True
            return tp > 0 and bar.high >= pos.entry + tp * pos.risk
        if bar.high >= pos.stop or tide > 0:
            return True
        return tp > 0 and bar.low <= pos.entry - tp * pos.risk

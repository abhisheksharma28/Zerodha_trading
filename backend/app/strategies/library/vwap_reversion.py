"""VWAP Mean Reversion — fade intraday extension from the session VWAP.

A desk-standard intraday idea: within a session, price that stretches a long
way from the volume-weighted average price tends to be pulled back toward
it. This template buys when price is ``entry_dev`` bands below the running
session VWAP (sells the mirror if ``allow_short``), targets a return to
VWAP, and squares off before the close.

Not guaranteed profitable. On a strong trend day price rides far from VWAP
for hours and never comes back; the stop and the end-of-day flat are the
protection. Validate out-of-sample with realistic intraday costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Session:
    day: date
    idx: int
    pv: float          # cumulative price*volume
    vol: float         # cumulative volume


@dataclass
class _Open:
    side: int
    entry: float
    stop: float


class VwapReversionStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "vwap-reversion"
    NAME: ClassVar[str] = "VWAP Mean Reversion"
    CATEGORY: ClassVar[str] = "Mean Reversion"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 40
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("5m", "15m", "60m")
    MIN_BARS_REQUIRED: ClassVar[int] = 40

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "warmup_bars": ParamSpec("integer", 6, "Bars into the session before any entry (let VWAP "
                                 "settle).", min=1, max=60),
        "entry_dev": ParamSpec("number", 2.0, "Enter when |close - VWAP| is this many ATRs.",
                               min=0.3, max=8.0),
        "exit_dev": ParamSpec("number", 0.3, "Exit when price is back within this many ATRs of VWAP.",
                              min=0.0, max=3.0),
        "atr_period": ParamSpec("integer", 20, "ATR window for the deviation band and the stop.",
                                min=2, max=100),
        "atr_stop_mult": ParamSpec("number", 1.5, "Hard stop distance in ATRs beyond entry.",
                                   min=0.3, max=8.0, group="risk"),
        "allow_short": ParamSpec("boolean", True, "Also fade extension above VWAP."),
        "session_bars": ParamSpec("integer", 75, "Bars in a full session (for the end-of-day flat).",
                                  min=10, max=400),
        "flat_before_close_bars": ParamSpec("integer", 3, "Square off this many bars before the "
                                            "session ends.", min=0, max=30, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(warmup_bars=10, entry_dev=2.5, exit_dev=0.4, atr_period=20,
                               atr_stop_mult=1.5, allow_short=False, session_bars=75,
                               flat_before_close_bars=4, product="MIS",
                               sizing_method="risk_per_trade", risk_per_trade_pct=0.4,
                               max_position_size_pct=15.0),
        "balanced": preset(warmup_bars=6, entry_dev=2.0, exit_dev=0.3, atr_period=20,
                           atr_stop_mult=1.5, allow_short=True, session_bars=75,
                           flat_before_close_bars=3, product="MIS",
                           sizing_method="risk_per_trade", risk_per_trade_pct=0.75,
                           max_position_size_pct=20.0),
        "aggressive": preset(warmup_bars=4, entry_dev=1.5, exit_dev=0.2, atr_period=14,
                             atr_stop_mult=1.2, allow_short=True, session_bars=75,
                             flat_before_close_bars=2, product="MIS",
                             sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Intraday: buys price stretched entry_dev ATRs below the running session "
                     "VWAP (sells the mirror), targets a return to VWAP, stops on further "
                     "extension, and is flat by the close."),
        logic=("Reset a cumulative VWAP each session. After warmup_bars, band = ATR(atr_period). "
               "Enter long when close <= VWAP - entry_dev x band (short when close >= VWAP + "
               "entry_dev x band and allow_short). Exit when |close - VWAP| <= exit_dev x band, "
               "the ATR stop is hit, or the session reaches session_bars - flat_before_close_bars."),
        timeframe="5m / 15m / 60m",
        market_types=["Liquid NSE equities", "index futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=False,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Intraday",
        risks=["Trend days: price stays far from VWAP for hours — a string of stops.",
               "Thin names have a jumpy VWAP and unreliable bands.",
               "High trade count makes it very sensitive to slippage and brokerage."],
        best_for="High-volume names on range-bound sessions.",
        warning="Counter-trend and intraday; size small and respect the stop.",
        required_data=["Intraday OHLCV with volume, at least atr_period bars into each session"],
        example=("On 5-minute RELIANCE: 40 minutes in, price is 2 ATRs below session VWAP -> buy; "
                 "exit when it tags VWAP or 1.5 ATRs lower. Flat 15 minutes before close. "
                 "Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._sess: dict[str, _Session] = {}
        self._open: dict[str, _Open] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        day = self.bar_dt(bar).date()
        s = self._sess.get(sym)
        if s is None or s.day != day:
            s = _Session(day=day, idx=0, pv=0.0, vol=0.0)
            self._sess[sym] = s
        s.idx += 1
        px = float(bar.close)
        vol = float(bar.volume) or 1.0
        s.pv += px * vol
        s.vol += vol
        vwap = s.pv / s.vol if s.vol > 0 else px

        a = atr(list(buf.highs), list(buf.lows), list(buf.closes), int(self.p["atr_period"]))
        if a is None or a <= 0:
            return
        band = a
        dev = (px - vwap) / band
        pos = self._open.get(sym)

        near_close = s.idx >= int(self.p["session_bars"]) - int(self.p["flat_before_close_bars"])

        if pos is not None:
            stop_hit = (pos.side == 1 and bar.low <= pos.stop) or (
                pos.side == -1 and bar.high >= pos.stop)
            reverted = abs(dev) <= float(self.p["exit_dev"])
            if stop_hit or reverted or near_close:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if near_close or s.idx <= int(self.p["warmup_bars"]):
            return
        ed = float(self.p["entry_dev"])
        side = 0
        if dev <= -ed:
            side = 1
        elif dev >= ed and self.p["allow_short"]:
            side = -1
        if side == 1 and not self.long_entries_allowed():
            return
        if side == 0:
            return
        risk = float(self.p["atr_stop_mult"]) * band
        qty = self.size_position(px, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == 1 else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(side=side, entry=px, stop=px - side * risk)

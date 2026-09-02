"""Donchian Channel Breakout — systematic trend-following breakout.

The Turtle-style channel breakout, generalised: enter when price closes
beyond the prior ``entry_period`` high/low (the current bar is excluded so
the signal is causal), exit on the opposite ``exit_period`` channel, an ATR
hard stop fixed to the ATR at entry, an optional ATR trailing stop, or an
optional time stop. Optional confirmation gates — relative volume, ATR
expansion and an ADX trend filter — cut the weakest breakouts.

Not guaranteed profitable. Breakout systems take many small losing trades
in range-bound markets and rely on a few large trends to pay for them;
validate out-of-sample and with realistic costs before any live use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import adx, atr, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _OpenPos:
    side: str  # "long" | "short"
    entry_price: float
    entry_index: int
    entry_atr: float  # stop distances are fixed to this, not a moving ATR
    extreme: float  # best price seen since entry (high for long, low for short)


class DonchianBreakoutStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "donchian-breakout"
    NAME: ClassVar[str] = "Donchian Breakout"
    CATEGORY: ClassVar[str] = "Trend"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "30m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "entry_period": ParamSpec(
            "integer", 20, "Channel lookback for the breakout entry (highest high / lowest low).",
            min=3, max=400,
        ),
        "exit_period": ParamSpec(
            "integer", 10, "Opposite-channel lookback used to exit an open position.",
            min=2, max=400,
        ),
        "breakout_on": ParamSpec(
            "enum", "close", "Which price must clear the channel: the bar close or its extreme.",
            choices=("close", "extreme"),
        ),
        "allow_short": ParamSpec("boolean", False, "Permit short breakouts (down through the lower channel)."),
        "atr_period": ParamSpec("integer", 14, "ATR lookback for stops and the expansion filter.",
                                min=2, max=100, group="risk"),
        "atr_stop_mult": ParamSpec(
            "number", 2.0, "Hard stop distance in ATRs, fixed to the ATR at entry (0 disables).",
            min=0.0, max=20.0, group="risk",
        ),
        "trailing_atr_mult": ParamSpec(
            "number", 3.0, "Trailing stop distance in ATRs from the best price since entry (0 disables).",
            min=0.0, max=20.0, group="risk",
        ),
        "max_holding_bars": ParamSpec(
            "integer", 0, "Force exit after this many bars (0 disables).", min=0, max=100_000,
            group="risk",
        ),
        "rvol_min": ParamSpec(
            "number", 0.0, "Minimum volume / SMA(volume, rvol_lookback) on the breakout bar (0 disables).",
            min=0.0, max=20.0, group="filter",
        ),
        "rvol_lookback": ParamSpec("integer", 20, "Lookback for the relative-volume average.",
                                   min=2, max=200, group="filter"),
        "atr_expansion_min": ParamSpec(
            "number", 0.0,
            "Minimum current ATR / SMA(ATR, atr_period) on the breakout bar (0 disables).",
            min=0.0, max=10.0, group="filter",
        ),
        "adx_min": ParamSpec(
            "number", 0.0, "Minimum ADX(adx_period) to allow an entry (0 disables the filter).",
            min=0.0, max=100.0, group="filter",
        ),
        "adx_period": ParamSpec("integer", 14, "ADX lookback for the trend filter.",
                                min=2, max=100, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            entry_period=55, exit_period=20, breakout_on="close", allow_short=False,
            atr_stop_mult=3.0, trailing_atr_mult=5.0, adx_min=20.0, rvol_min=1.2,
            sizing_method="risk_per_trade", risk_per_trade_pct=0.5, max_position_size_pct=10.0,
        ),
        "balanced": preset(
            entry_period=20, exit_period=10, breakout_on="close", allow_short=False,
            atr_stop_mult=2.0, trailing_atr_mult=3.0, adx_min=0.0, rvol_min=0.0,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.0, max_position_size_pct=20.0,
        ),
        "aggressive": preset(
            entry_period=15, exit_period=7, breakout_on="extreme", allow_short=True,
            atr_stop_mult=1.5, trailing_atr_mult=2.5, atr_expansion_min=1.1,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.5, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Buys N-period channel breakouts and rides the trend with ATR-based risk control, "
            "exiting on the opposite (shorter) channel or a stop."
        ),
        logic=(
            "Each bar, compute the highest high and lowest low of the prior entry_period bars "
            "(current bar excluded). Go long when the chosen price (close or bar high) exceeds the "
            "prior high; mirror for shorts when allow_short is set. Optional gates: relative volume "
            ">= rvol_min, ATR expansion >= atr_expansion_min, ADX >= adx_min, and the benchmark "
            "regime filter. Exit on a break of the opposite exit_period channel, a hard ATR stop "
            "fixed to the ATR at entry, an optional ATR trailing stop, or max_holding_bars."
        ),
        timeframe="day / 60minute / 15minute",
        market_types=["NSE equities", "index & stock futures", "liquid ETFs"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Swing / Positional",
        risks=[
            "Frequent small losses from false breakouts in range-bound markets.",
            "Gap moves through the ATR stop produce larger-than-modelled losses.",
            "Performance is concentrated in a few large trends; long flat/negative stretches between them.",
        ],
        best_for="Trend-following on instruments prone to sustained directional moves.",
        warning="Breakout strategies suffer strings of small losses between the few trends that pay off.",
        required_data=["OHLCV bars per instrument, at least entry_period + atr_period + rvol_lookback bars"],
        example=(
            "On daily bars with entry_period=20, exit_period=10: a long is taken the day price "
            "closes above the highest high of the prior 20 sessions, and is exited when price "
            "closes below the lowest low of the prior 10 sessions or hits a 2x ATR stop. "
            "Mechanics only — not an expected return."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._open: dict[str, _OpenPos] = {}
        self._seen: dict[str, int] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]

        entry_n = int(self.p["entry_period"])
        exit_n = int(self.p["exit_period"])
        atr_n = int(self.p["atr_period"])
        highs = list(buf.highs)
        lows = list(buf.lows)
        closes = list(buf.closes)
        need = max(entry_n, exit_n, atr_n, int(self.p["rvol_lookback"])) + 2
        if len(closes) < need:
            return

        atr_now = atr(highs, lows, closes, atr_n)
        if atr_now is None or atr_now <= 0:
            return

        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            pos.extreme = max(pos.extreme, highs[-1]) if pos.side == "long" else min(pos.extreme, lows[-1])
            if self._should_exit(sym, pos, price, highs, lows, closes, exit_n, idx):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        # flat -> look for a breakout. Prior channel EXCLUDES the current bar.
        prior_high = max(highs[-(entry_n + 1):-1])
        prior_low = min(lows[-(entry_n + 1):-1])
        trigger = closes[-1] if self.p["breakout_on"] == "close" else None
        long_px = trigger if trigger is not None else highs[-1]
        short_px = trigger if trigger is not None else lows[-1]

        long_break = long_px > prior_high
        short_break = self.p["allow_short"] and short_px < prior_low
        if not (long_break or short_break):
            return
        if not self._confirmed(buf, highs, lows, closes, atr_now, atr_n):
            return

        if long_break:
            if not self.long_entries_allowed():
                return
            self._enter(sym, "long", price, atr_now, idx)
        elif short_break:
            self._enter(sym, "short", price, atr_now, idx)

    # --- filters -----------------------------------------------------

    def _confirmed(self, buf, highs, lows, closes, atr_now: float, atr_n: int) -> bool:
        rvol_min = float(self.p["rvol_min"])
        if rvol_min > 0:
            vols = list(buf.volumes)
            avg = sma(vols, int(self.p["rvol_lookback"]))
            if not avg or avg <= 0 or (vols[-1] / avg) < rvol_min:
                return False

        exp_min = float(self.p["atr_expansion_min"])
        if exp_min > 0:
            atr_hist = [
                a for a in (
                    atr(highs[: i + 1], lows[: i + 1], closes[: i + 1], atr_n)
                    for i in range(len(closes) - atr_n, len(closes))
                )
                if a is not None
            ]
            avg_atr = sum(atr_hist) / len(atr_hist) if atr_hist else None
            if not avg_atr or avg_atr <= 0 or (atr_now / avg_atr) < exp_min:
                return False

        adx_min = float(self.p["adx_min"])
        if adx_min > 0:
            adx_now = adx(highs, lows, closes, int(self.p["adx_period"]))
            if adx_now is None or adx_now < adx_min:
                return False
        return True

    # --- entry / exit ----------------------------------------------

    def _enter(self, sym: str, side: str, price: float, atr_now: float, idx: int) -> None:
        stop_dist = float(self.p["atr_stop_mult"]) * atr_now or price * 0.02
        qty = self.size_position(price, stop_distance=stop_dist, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _OpenPos(side=side, entry_price=price, entry_index=idx,
                                   entry_atr=atr_now, extreme=price)

    def _should_exit(
        self, sym: str, pos: _OpenPos, price: float,
        highs: list[float], lows: list[float], closes: list[float], exit_n: int, idx: int,
    ) -> bool:
        hard = float(self.p["atr_stop_mult"]) * pos.entry_atr
        trail = float(self.p["trailing_atr_mult"]) * pos.entry_atr
        # opposite channel excludes the current bar
        opp_low = min(lows[-(exit_n + 1):-1])
        opp_high = max(highs[-(exit_n + 1):-1])
        if pos.side == "long":
            if closes[-1] < opp_low:
                return True
            if hard and price <= pos.entry_price - hard:
                return True
            if trail and price <= pos.extreme - trail:
                return True
        else:
            if closes[-1] > opp_high:
                return True
            if hard and price >= pos.entry_price + hard:
                return True
            if trail and price >= pos.extreme + trail:
                return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and (idx - pos.entry_index) >= max_hold)

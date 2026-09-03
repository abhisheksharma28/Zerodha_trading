"""Volatility-Contraction Breakout — buy the release of a long, tight base.

After a stock spends weeks in a narrow, quieting range (a Volatility
Contraction Pattern — Minervini; Darvas boxes; Wyckoff accumulation), the
first decisive push above the range often starts a larger move. This
template waits for a genuine multi-week contraction, then enters on the
breakout bar (or the confirming green day) provided price has not already
run too far past the level. The stop sits on the base; the target is a
multiple of that risk.

Not guaranteed profitable. False breakouts from bases are common and the
market regime matters a lot. Validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, rolling_volatility, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    entry: float
    stop: float
    target: float
    entry_index: int
    range_high: float


class VolatilityContractionBreakoutStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "volatility-contraction-breakout"
    NAME: ClassVar[str] = "Volatility-Contraction Breakout"
    CATEGORY: ClassVar[str] = "Breakout"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 60
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 80

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "contraction_window": ParamSpec("integer", 25, "Bars the base must span (~25 = five "
                                        "weeks). The contraction is measured over this window.",
                                        min=10, max=150),
        "contraction_pct": ParamSpec("number", 12.0, "The base's high-to-low range must be within "
                                     "this % of price to count as tight.", min=2.0, max=40.0),
        "vol_ratio_max": ParamSpec("number", 0.85, "Recent realised vol / earlier realised vol "
                                   "across the base must be below this (volatility is compressing).",
                                   min=0.3, max=1.2),
        "green_days": ParamSpec("integer", 1, "Consecutive up days required to confirm the "
                                "breakout (1 = act on the break bar).", min=1, max=3),
        "max_extension_pct": ParamSpec("number", 4.0, "Skip if price is already more than this % "
                                       "above the base high (the move has gone).", min=0.5,
                                       max=20.0),
        "atr_period": ParamSpec("integer", 14, "ATR window for the structural stop.", min=2,
                                max=100, group="risk"),
        "atr_stop_mult": ParamSpec("number", 1.5, "Stop = min(base low, entry - this x ATR).",
                                   min=0.3, max=8.0, group="risk"),
        "target_r": ParamSpec("number", 2.5, "Target distance as a multiple of the entry-to-stop "
                              "risk (>= 2 keeps R:R >= 1:2).", min=1.0, max=10.0, group="risk"),
        "max_holding_bars": ParamSpec("integer", 40, "Force exit after N bars (0 disables).",
                                      min=0, max=250, group="risk"),
        "trend_ma_period": ParamSpec("integer", 0, "Optional: only take breakouts while close > "
                              "SMA(this) (0 disables).", min=0, max=400, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(contraction_window=35, contraction_pct=10.0, vol_ratio_max=0.75,
                               green_days=2, max_extension_pct=3.0, atr_stop_mult=1.5,
                               target_r=3.0, max_holding_bars=40, trend_ma_period=200,
                               product="CNC", sizing_method="risk_per_trade",
                               risk_per_trade_pct=0.5, max_position_size_pct=15.0),
        "balanced": preset(contraction_window=25, contraction_pct=12.0, vol_ratio_max=0.85,
                           green_days=1, max_extension_pct=4.0, atr_stop_mult=1.5, target_r=2.5,
                           max_holding_bars=40, trend_ma_period=0, product="CNC",
                           sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
                           max_position_size_pct=20.0),
        "aggressive": preset(contraction_window=18, contraction_pct=16.0, vol_ratio_max=1.0,
                             green_days=1, max_extension_pct=6.0, atr_stop_mult=2.0, target_r=2.0,
                             max_holding_bars=25, trend_ma_period=0, product="MIS",
                             sizing_method="risk_per_trade", risk_per_trade_pct=1.5,
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Waits for a multi-week tight range with compressing volatility, then buys "
                     "the breakout above the range high if price has not already extended past it; "
                     "stop on the base, target a multiple of risk."),
        logic=("A base is valid when, over contraction_window bars, (max(high) - min(low)) / close "
               "<= contraction_pct/100 AND realised vol over the recent half of the window is <= "
               "vol_ratio_max x realised vol over the earlier half. On a bar that closes above the "
               "base high with green_days consecutive up closes, and close <= base_high x "
               "(1 + max_extension_pct/100), and (trend_ma_period == 0 or close > "
               "SMA(trend_ma_period)): go long. Stop = min(base low, entry - atr_stop_mult x ATR); "
               "target = entry + target_r x (entry - stop). Exit on target, stop, a close back "
               "below the base high, or max_holding_bars."),
        timeframe="day",
        market_types=["NSE cash equities with real liquidity"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Swing",
        risks=["Bases fail often — a close back inside the range is the tell; honour the exit.",
               "Works far better in a constructive market than a corrective one.",
               "Illiquid names gap through the stop; the liquidity screen matters."],
        best_for="Constructive markets where leaders build tight bases before advancing.",
        warning="A breakout is a probability, not a certainty; the base-low stop is the risk.",
        required_data=["Daily OHLCV per instrument, at least contraction_window + atr_period + a "
                       "margin of bars"],
        example=("On daily PERSISTENT: five weeks in a 9% range with vol falling, then a green "
                 "close 1% above the range high and above the 200-SMA -> long; stop at the range "
                 "low, target 2.5x that distance. Mechanics only, not advice."),
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
        highs = list(buf.highs)
        lows = list(buf.lows)
        w = int(self.p["contraction_window"])
        na = int(self.p["atr_period"])
        if len(closes) < max(w, na, int(self.p["trend_ma_period"])) + 3:
            return

        price = closes[-1]
        pos = self._open.get(sym)
        if pos is not None:
            hold = int(self.p["max_holding_bars"])
            failed = price < pos.range_high
            if (bar.high >= pos.target or bar.low <= pos.stop or failed
                    or (hold > 0 and idx - pos.entry_index >= hold)):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        gd = int(self.p["green_days"])
        if len(closes) < w + gd + 2:
            return
        # the last `gd` bars are the confirming push; the base is the window
        # that ends just before them, so the push does not pollute it.
        base_h = highs[-(w + gd):-gd]
        base_l = lows[-(w + gd):-gd]
        base_c = closes[-(w + gd):-gd]
        base_high = max(base_h)
        base_low = min(base_l)
        if base_high <= 0 or price <= 0:
            return
        rng_pct = (base_high - base_low) / price * 100.0
        if rng_pct > float(self.p["contraction_pct"]):
            return

        half = max(3, w // 2)
        v_recent = rolling_volatility(base_c[-half:], half - 1)
        v_early = rolling_volatility(base_c[:half] or base_c, half - 1)
        if v_recent is None or v_early is None or v_early <= 0:
            return
        if v_recent / v_early > float(self.p["vol_ratio_max"]):
            return

        if any(closes[-k] <= closes[-k - 1] for k in range(1, gd + 1)):
            return
        if price <= base_high:
            return
        if price > base_high * (1 + float(self.p["max_extension_pct"]) / 100.0):
            return
        tm = int(self.p["trend_ma_period"])
        if tm > 0:
            m = sma(closes, tm)
            if m is None or price <= m:
                return
        if not self.long_entries_allowed():
            return

        a = atr(highs, lows, closes, na)
        if a is None or a <= 0:
            return
        stop = min(base_low, price - float(self.p["atr_stop_mult"]) * a)
        risk = price - stop
        if risk <= 0:
            return
        target = price + float(self.p["target_r"]) * risk
        qty = self.size_position(price, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(entry=price, stop=stop, target=target, entry_index=idx,
                                range_high=base_high)

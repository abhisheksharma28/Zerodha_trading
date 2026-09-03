"""Z-Score Regime Mean-Reversion — buy deep oversold dips, but only while
the long-term trend regime is up.

Adapted from Poudel & Paudel (2025), "Quantitative Trading Strategy,
Backtesting, and Performance Analysis" (NEPSE): a long-only rule set that
combines a Z-Score deviation trigger and an RSI oversold confirmation with
a long moving-average **regime filter** — trade only when price is above
the regime MA, otherwise stand in cash. Realistic constraints (cool-down
after an exit, a hard ATR stop, an optional take-profit) are built in.

Not guaranteed profitable. Mean-reversion buys falling prices; the regime
filter and the stop are the only things standing between it and a trending
sell-off. Validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, rsi, sma, zscore
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    entry: float
    stop: float
    entry_index: int
    risk: float


class ZScoreRegimeStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "zscore-regime-mr"
    NAME: ClassVar[str] = "Z-Score Regime Mean Reversion"
    CATEGORY: ClassVar[str] = "Mean Reversion"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 25
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "regime_ma": ParamSpec("integer", 240, "Long moving average; longs only while price is above it.",
                               min=20, max=400),
        "zscore_lookback": ParamSpec("integer", 20, "Window for the Z-Score of price.", min=5, max=120),
        "entry_z": ParamSpec("number", -2.0, "Buy when the Z-Score falls to or below this.",
                             min=-6.0, max=-0.5),
        "exit_z": ParamSpec("number", -0.3, "Exit when the Z-Score recovers to or above this.",
                            min=-3.0, max=3.0),
        "rsi_period": ParamSpec("integer", 14, "RSI period for the oversold confirmation.", min=2, max=100),
        "rsi_max": ParamSpec("number", 35.0, "Also require RSI <= this on entry (0 disables the check).",
                             min=0.0, max=100.0, group="filter"),
        "atr_period": ParamSpec("integer", 14, "ATR period for the hard stop.", min=2, max=100, group="risk"),
        "atr_stop_mult": ParamSpec("number", 2.5, "Hard stop distance in ATRs.", min=0.5, max=10.0,
                                   group="risk"),
        "take_profit_r": ParamSpec("number", 2.0, "Take profit at this multiple of initial risk "
                                   "(0 disables).", min=0.0, max=20.0, group="risk"),
        "cooldown_bars": ParamSpec("integer", 3, "Bars to wait after an exit before re-entering.",
                                   min=0, max=50, group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 disables).",
                                      min=0, max=100_000, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(regime_ma=240, entry_z=-2.5, exit_z=-0.2, rsi_max=30.0,
                               atr_stop_mult=3.0, take_profit_r=1.5, cooldown_bars=5, product="CNC",
                               sizing_method="risk_per_trade", risk_per_trade_pct=0.5,
                               max_position_size_pct=15.0),
        "balanced": preset(regime_ma=240, entry_z=-2.0, exit_z=-0.3, rsi_max=35.0,
                           atr_stop_mult=2.5, take_profit_r=2.0, cooldown_bars=3, product="CNC",
                           sizing_method="risk_per_trade", risk_per_trade_pct=1.0,
                           max_position_size_pct=20.0),
        "aggressive": preset(regime_ma=150, entry_z=-1.6, exit_z=0.0, rsi_max=45.0,
                             atr_stop_mult=2.0, take_profit_r=0.0, cooldown_bars=1, product="MIS",
                             sizing_method="risk_per_trade", risk_per_trade_pct=1.5,
                             max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Buys deep Z-Score / RSI oversold dips, but only while price is above a long "
                     "regime moving average; exits on Z-Score reversion, a hard ATR stop, an "
                     "optional take-profit, or a regime break."),
        logic=("Per instrument: regime = close > SMA(regime_ma). With no position and the regime up, "
               "enter long when Z-Score(zscore_lookback) <= entry_z and (rsi_max == 0 or "
               "RSI(rsi_period) <= rsi_max), after any cool-down has elapsed. Stop = entry - "
               "atr_stop_mult x ATR. Exit on: Z-Score >= exit_z, stop hit, take_profit_r x risk "
               "reached, max_holding_bars, or the regime breaking (close < SMA(regime_ma))."),
        timeframe="day / 60minute",
        market_types=["NSE cash equities", "index / stock futures"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Swing",
        risks=["Mean reversion buys weakness — a trending decline through the regime MA can still "
               "produce a run of stops.",
               "The regime MA is a lagging filter; it turns after a big drawdown, not before it.",
               "Thin or gappy names blow through the ATR stop."],
        best_for="Liquid names that oscillate around a rising trend.",
        warning="Buys falling prices. The regime filter and the ATR stop are the only risk controls.",
        required_data=["OHLCV bars per instrument, at least regime_ma + a few bars"],
        example=("On daily RELIANCE bars: price is above its 240-day SMA, the 20-day Z-Score drops "
                 "to -2.1 and RSI is 32 -> buy. Z-Score climbs back to -0.2 -> exit. Mechanics only, "
                 "not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._open: dict[str, _Open] = {}
        self._seen: dict[str, int] = {}
        self._last_exit: dict[str, int] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        closes = list(buf.closes)
        need = max(int(self.p["regime_ma"]), int(self.p["zscore_lookback"]),
                   int(self.p["rsi_period"]), int(self.p["atr_period"])) + 2
        if len(closes) < need:
            return

        ma = sma(closes, int(self.p["regime_ma"]))
        z = zscore(closes, int(self.p["zscore_lookback"]))
        r = rsi(closes, int(self.p["rsi_period"]))
        a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        if ma is None or z is None or a is None:
            return
        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            exit_now = (
                bar.low <= pos.stop
                or z >= float(self.p["exit_z"])
                or price < ma
                or (float(self.p["take_profit_r"]) > 0
                    and bar.high >= pos.entry + float(self.p["take_profit_r"]) * pos.risk)
                or (int(self.p["max_holding_bars"]) > 0
                    and idx - pos.entry_index >= int(self.p["max_holding_bars"]))
            )
            if exit_now:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
                self._last_exit[sym] = idx
            return

        if idx - self._last_exit.get(sym, -10_000) < int(self.p["cooldown_bars"]):
            return
        if price <= ma or not self.long_entries_allowed():
            return
        rsi_ok = float(self.p["rsi_max"]) <= 0 or (r is not None and r <= float(self.p["rsi_max"]))
        if z > float(self.p["entry_z"]) or not rsi_ok:
            return
        risk = float(self.p["atr_stop_mult"]) * a or price * 0.03
        qty = self.size_position(price, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(entry=price, stop=price - risk, entry_index=idx, risk=risk)

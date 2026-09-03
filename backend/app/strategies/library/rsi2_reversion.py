"""RSI(2) Mean Reversion — buy short-term oversold in a long-term uptrend.

A very short RSI (period 2 by default) tags brief washouts. Only act on the
long side while price is above a long moving average (the regime filter);
exit on a snap-back (RSI recovers, or price closes back above a fast MA).
A classic short-hold pullback method popularised for US equity indices;
here it is re-calibrated and exposed as parameters, not hard-coded.

Not guaranteed profitable. It buys falling knives by design; the regime
filter and a hard stop are the only protection. Validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, rsi, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    entry: float
    stop: float
    entry_index: int


class Rsi2ReversionStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "rsi2-reversion"
    NAME: ClassVar[str] = "RSI(2) Mean Reversion"
    CATEGORY: ClassVar[str] = "Mean Reversion"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m")
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "rsi_period": ParamSpec("integer", 2, "RSI lookback (short).", min=2, max=20),
        "entry_rsi": ParamSpec("number", 10.0, "Buy when RSI <= this.", min=1.0, max=40.0),
        "exit_rsi": ParamSpec("number", 60.0, "Exit when RSI >= this.", min=20.0, max=95.0),
        "regime_window": ParamSpec("integer", 200, "Only buy while close > SMA(this).", min=20, max=400),
        "exit_ma_period": ParamSpec("integer", 5, "Also exit when close > SMA(this).", min=2, max=50),
        "max_holding_bars": ParamSpec("integer", 10, "Force exit after N bars (0 disables).",
                                      min=0, max=200, group="risk"),
        "atr_period": ParamSpec("integer", 14, "ATR period for the hard stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 3.0, "Hard stop distance in ATRs.", min=0.5, max=10.0,
                                   group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(rsi_period=2, entry_rsi=5.0, exit_rsi=65.0, regime_window=200,
                               exit_ma_period=5, max_holding_bars=8, atr_stop_mult=3.5, product="CNC",
                               sizing_method="fixed_capital", max_position_size_pct=20.0),
        "balanced": preset(rsi_period=2, entry_rsi=10.0, exit_rsi=60.0, regime_window=200,
                           exit_ma_period=5, max_holding_bars=10, atr_stop_mult=3.0, product="CNC",
                           sizing_method="fixed_capital", max_position_size_pct=25.0),
        "aggressive": preset(rsi_period=3, entry_rsi=15.0, exit_rsi=55.0, regime_window=100,
                             exit_ma_period=3, max_holding_bars=6, atr_stop_mult=2.5, product="MIS",
                             sizing_method="fixed_capital", max_position_size_pct=30.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Buys a short-RSI washout while price is above a long MA; exits on the "
                     "snap-back (RSI recovers or close > a fast MA), a time stop, or a hard ATR stop."),
        logic=("Long only while close > SMA(regime_window). Enter when RSI(rsi_period) <= entry_rsi. "
               "Exit when RSI >= exit_rsi OR close > SMA(exit_ma_period) OR max_holding_bars elapsed OR "
               "the ATR stop (entry - atr_stop_mult x ATR) is hit."),
        timeframe="day / 60m",
        market_types=["NSE cash equities", "index ETFs"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Short swing",
        risks=["Buys into weakness — a trend that keeps falling through the regime MA produces "
               "a run of stops.",
               "Short holding periods make it sensitive to costs and slippage.",
               "Crowded, well-known logic; edge may have decayed."],
        best_for="Liquid names that dip and recover inside an uptrend.",
        warning="Mean reversion against the immediate move; size it small.",
        required_data=["OHLCV bars per instrument, at least regime_window + a few bars"],
        example="On daily HDFCBANK above its 200-SMA: RSI(2) prints 7 -> buy; RSI(2) back to 62 -> exit.",
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
        if len(closes) < int(self.p["regime_window"]) + 2:
            return
        r = rsi(closes, int(self.p["rsi_period"]))
        regime = sma(closes, int(self.p["regime_window"]))
        exit_ma = sma(closes, int(self.p["exit_ma_period"]))
        a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        if r is None or regime is None or a is None:
            return
        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            hold = int(self.p["max_holding_bars"])
            exit_now = (
                r >= float(self.p["exit_rsi"])
                or (exit_ma is not None and price > exit_ma)
                or bar.low <= pos.stop
                or (hold > 0 and idx - pos.entry_index >= hold)
            )
            if exit_now:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if price <= regime or r > float(self.p["entry_rsi"]) or not self.long_entries_allowed():
            return
        risk = float(self.p["atr_stop_mult"]) * a
        qty = self.size_position(price, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY", qty, exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _Open(entry=price, stop=price - risk, entry_index=idx)

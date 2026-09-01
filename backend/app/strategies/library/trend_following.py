"""Trend Following — systematic moving-average trend strategy.

More than a bare MA crossover: entries require the crossover *and* price on
the correct side of the slow MA *and* per-bar volatility inside a
configured band *and* a minimum trend-strength (MA separation). Exits cover
the opposite crossover, an ATR stop, an optional ATR trailing stop, an
optional take-profit, and an optional maximum holding period. Position
sizing is pluggable (see TemplateStrategy.size_position), including
volatility-adjusted sizing so exposure falls as volatility rises.

Not guaranteed profitable. Trend strategies endure long stretches of
whipsaw in range-bound markets; validate out-of-sample and with realistic
costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, crossed_above, crossed_below, rolling_volatility
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _OpenPos:
    side: str  # "long" | "short"
    entry_price: float
    entry_index: int
    entry_atr: float  # ATR at entry — stop distances are fixed to this, not a moving ATR
    extreme: float  # highest close since entry (long) / lowest (short)


class TrendFollowingStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "trend-following"
    NAME: ClassVar[str] = "Trend Following"
    CATEGORY: ClassVar[str] = "Trend"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 60

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "ma_type": ParamSpec("enum", "ema", "Moving-average type.", choices=("sma", "ema")),
        "fast_period": ParamSpec("integer", 20, "Fast MA lookback.", min=2, max=200),
        "slow_period": ParamSpec("integer", 50, "Slow MA lookback.", min=3, max=400),
        "atr_period": ParamSpec("integer", 14, "ATR lookback.", min=2, max=100, group="risk"),
        "trend_strength_min_pct": ParamSpec(
            "number", 0.0, "Minimum |fastMA - slowMA| / slowMA (%) to allow entry.",
            min=0.0, max=50.0, group="filter",
        ),
        "vol_min_pct": ParamSpec(
            "number", 0.0, "Minimum per-bar realized volatility (%) to allow entry.",
            min=0.0, max=100.0, group="filter",
        ),
        "vol_max_pct": ParamSpec(
            "number", 100.0, "Maximum per-bar realized volatility (%) to allow entry.",
            min=0.0, max=1000.0, group="filter",
        ),
        "use_price_filter": ParamSpec(
            "boolean", True, "Require price on the correct side of the slow MA.", group="filter",
        ),
        "allow_short": ParamSpec("boolean", False, "Permit short entries."),
        "atr_stop_mult": ParamSpec(
            "number", 2.5, "Hard stop distance in ATRs (0 disables).", min=0.0, max=20.0,
            group="risk",
        ),
        "trailing_atr_mult": ParamSpec(
            "number", 0.0, "Trailing stop distance in ATRs (0 disables).", min=0.0, max=20.0,
            group="risk",
        ),
        "take_profit_pct": ParamSpec(
            "number", 0.0, "Take-profit distance (%) from entry (0 disables).",
            min=0.0, max=500.0, group="risk",
        ),
        "max_holding_bars": ParamSpec(
            "integer", 0, "Force exit after this many bars (0 disables).", min=0, max=100_000,
            group="risk",
        ),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            ma_type="ema", fast_period=30, slow_period=100, atr_stop_mult=3.0,
            trend_strength_min_pct=1.0, use_price_filter=True, allow_short=False,
            sizing_method="volatility_adjusted", target_volatility_pct=1.5,
            max_position_size_pct=10.0,
        ),
        "balanced": preset(
            ma_type="ema", fast_period=20, slow_period=50, atr_stop_mult=2.5,
            trailing_atr_mult=4.0, trend_strength_min_pct=0.5, allow_short=False,
            sizing_method="fixed_quantity", fixed_quantity=1,
        ),
        "aggressive": preset(
            ma_type="ema", fast_period=10, slow_period=30, atr_stop_mult=2.0,
            trailing_atr_mult=3.0, trend_strength_min_pct=0.0, allow_short=True,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.5, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Goes with the prevailing trend: long when a fast moving average is above a slow one "
            "and price confirms, flat/short otherwise, with ATR-based risk control."
        ),
        logic=(
            "Compute a fast and slow MA (SMA or EMA). Enter long on a fast-above-slow crossover "
            "when price is above the slow MA, MA separation exceeds trend_strength_min_pct, and "
            "per-bar volatility is inside [vol_min_pct, vol_max_pct]. Mirror for shorts when "
            "allow_short is set. Exit on the opposite crossover, an ATR hard stop, an optional ATR "
            "trailing stop, an optional take-profit, or a maximum holding period."
        ),
        timeframe="day / 60minute / 15minute",
        market_types=["NSE equities", "index futures", "liquid ETFs"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Swing / Positional",
        risks=[
            "Prolonged whipsaw losses in range-bound, choppy markets.",
            "Late entries and give-back of open profit around trend reversals.",
            "Gap moves through the ATR stop cause larger-than-modelled losses.",
        ],
        best_for="Swing and positional trading of instruments that exhibit persistent trends.",
        warning="Trend strategies can experience prolonged periods of whipsaw.",
        required_data=["OHLCV bars for each instrument, at least slow_period + atr_period bars"],
        example=(
            "On daily RELIANCE bars with EMA(20/50): a long is taken the day the 20 EMA closes "
            "above the 50 EMA while price holds above the 50 EMA, and is exited on the reverse "
            "cross or a 2.5x ATR stop, whichever comes first. This describes mechanics only, not "
            "expected returns."
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

        slow_n = int(self.p["slow_period"])
        fast_n = int(self.p["fast_period"])
        atr_n = int(self.p["atr_period"])
        closes = list(buf.closes)
        if len(closes) < max(slow_n, atr_n) + 2:
            return

        kind = self.p["ma_type"]
        fast_now = self._ma(closes, fast_n, kind)
        slow_now = self._ma(closes, slow_n, kind)
        fast_prev = self._ma(closes[:-1], fast_n, kind)
        slow_prev = self._ma(closes[:-1], slow_n, kind)
        atr_now = atr(list(buf.highs), list(buf.lows), closes, atr_n)
        if (
            fast_now is None
            or slow_now is None
            or fast_prev is None
            or slow_prev is None
            or atr_now is None
        ):
            return

        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            pos.extreme = max(pos.extreme, price) if pos.side == "long" else min(pos.extreme, price)
            if self._should_exit(sym, pos, price, fast_prev, slow_prev, fast_now, slow_now, idx):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        # flat -> look for an entry
        strength = abs(fast_now - slow_now) / slow_now * 100.0 if slow_now else 0.0
        if strength < float(self.p["trend_strength_min_pct"]):
            return
        vol = rolling_volatility(closes, 20)
        if vol is not None:
            vpct = vol * 100.0
            if vpct < float(self.p["vol_min_pct"]) or vpct > float(self.p["vol_max_pct"]):
                return

        price_ok_long = (not self.p["use_price_filter"]) or price > slow_now
        price_ok_short = (not self.p["use_price_filter"]) or price < slow_now

        if crossed_above(fast_prev, slow_prev, fast_now, slow_now) and price_ok_long:
            if not self.long_entries_allowed():
                return
            self._enter(sym, "long", price, atr_now, idx)
        elif (
            self.p["allow_short"]
            and crossed_below(fast_prev, slow_prev, fast_now, slow_now)
            and price_ok_short
        ):
            self._enter(sym, "short", price, atr_now, idx)

    # --- helpers -------------------------------------------------------

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
        fast_prev: float, slow_prev: float, fast_now: float, slow_now: float, idx: int,
    ) -> bool:
        # Stop distances are fixed to the ATR at entry so a violent bar can't
        # widen the stop out from under an open position.
        hard = float(self.p["atr_stop_mult"]) * pos.entry_atr
        trail = float(self.p["trailing_atr_mult"]) * pos.entry_atr
        tp = float(self.p["take_profit_pct"]) / 100.0
        if pos.side == "long":
            if crossed_below(fast_prev, slow_prev, fast_now, slow_now):
                return True
            if hard and price <= pos.entry_price - hard:
                return True
            if trail and price <= pos.extreme - trail:
                return True
            if tp and price >= pos.entry_price * (1 + tp):
                return True
        else:
            if crossed_above(fast_prev, slow_prev, fast_now, slow_now):
                return True
            if hard and price >= pos.entry_price + hard:
                return True
            if trail and price >= pos.extreme + trail:
                return True
            if tp and price <= pos.entry_price * (1 - tp):
                return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and (idx - pos.entry_index) >= max_hold)

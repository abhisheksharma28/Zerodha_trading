"""Regime-Adaptive — one strategy that switches its own sub-model by the
detected market regime.

Each bar it classifies a regime from trend strength (ADX), a Kaufman
efficiency ratio, a moving-average slope and a realised-volatility
percentile — on an optional benchmark symbol, else on the instrument
itself — into TRENDING / RANGING / HIGH_VOL. It then applies:

* TRENDING  -> a Donchian-style breakout entry in the trend direction;
* RANGING   -> a Z-score mean-reversion entry that fades extremes;
* HIGH_VOL  -> stand aside (optional: a wider-stop breakout).

Positions are exited on an ATR stop, an optional ATR trailing stop, the
sub-model's own exit (opposite channel for trend, Z back to ~0 for
mean-reversion), a max holding period, or a regime flip.

This is a *behaviour switch* inside one strategy, NOT a capital allocator
that runs the other library templates as separate deployments.

Not guaranteed profitable. Regime labels lag and flip around their
thresholds; validate out-of-sample.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import adx, atr, rolling_volatility, zscore
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


def _efficiency_ratio(closes: list[float], period: int) -> float:
    if len(closes) < period + 1:
        return 0.0
    net = abs(closes[-1] - closes[-1 - period])
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(len(closes) - period, len(closes)))
    return net / path if path > 0 else 0.0


def _pctile(hist: deque[float], v: float) -> float:
    return 100.0 * sum(1 for h in hist if h <= v) / len(hist) if hist else 50.0


@dataclass
class _OpenPos:
    side: str
    model: str  # "trend" | "meanrev" | "breakout"
    entry_price: float
    entry_index: int
    entry_atr: float
    extreme: float


@dataclass
class _St:
    vol_hist: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    seen: int = 0


class RegimeAdaptiveStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "regime-adaptive"
    NAME: ClassVar[str] = "Regime-Adaptive"
    CATEGORY: ClassVar[str] = "Adaptive"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m")
    MIN_BARS_REQUIRED: ClassVar[int] = 90

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "benchmark_symbol": ParamSpec("string", "",
                                      "Optional market-regime benchmark tradingsymbol in the "
                                      "stream. Blank = classify each instrument on itself."),
        # --- regime classification ---
        "adx_period": ParamSpec("integer", 14, "ADX lookback (trend strength).", min=2, max=100),
        "adx_trend_min": ParamSpec("number", 25.0, "ADX at/above this = trend candidate.",
                                   min=5.0, max=100.0),
        "er_period": ParamSpec("integer", 20, "Kaufman efficiency-ratio lookback.", min=3, max=200),
        "er_trend_min": ParamSpec("number", 0.35, "Efficiency ratio at/above this = clean trend.",
                                  min=0.0, max=1.0),
        "slope_ma_period": ParamSpec("integer", 50, "MA whose slope sets the trend direction.",
                                     min=3, max=400),
        "slope_lookback": ParamSpec("integer", 10, "Bars over which the MA slope is measured.",
                                    min=1, max=100),
        "vol_lookback": ParamSpec("integer", 20, "Realised-volatility window.", min=5, max=200),
        "vol_percentile_lookback": ParamSpec("integer", 252,
                                             "History used to rank realised volatility.",
                                             min=30, max=1000),
        "high_vol_pct": ParamSpec("number", 80.0,
                                  "Vol percentile at/above this = HIGH_VOL regime.",
                                  min=10.0, max=100.0),
        # --- which regimes trade ---
        "trade_trending": ParamSpec("boolean", True, "Take trend breakouts in TRENDING regime."),
        "trade_ranging": ParamSpec("boolean", True, "Take mean-reversion in RANGING regime."),
        "trade_high_vol": ParamSpec("boolean", False,
                                    "Take a wider-stop breakout in HIGH_VOL regime.", group="filter"),
        "exit_on_regime_flip": ParamSpec("boolean", True,
                                         "Close a position when the regime no longer matches its "
                                         "sub-model.", group="risk"),
        # --- sub-model params ---
        "breakout_period": ParamSpec("integer", 20, "Trend breakout channel.", min=3, max=300),
        "breakout_exit_period": ParamSpec("integer", 10, "Trend exit channel.", min=2, max=300),
        "mr_lookback": ParamSpec("integer", 20, "Mean-reversion Z-score window.", min=3, max=300),
        "mr_entry_z": ParamSpec("number", 2.0, "Absolute Z to enter mean-reversion.",
                                min=0.5, max=10.0),
        "mr_exit_z": ParamSpec("number", 0.3, "Z (toward 0) to exit mean-reversion.",
                               min=0.0, max=10.0),
        "allow_short": ParamSpec("boolean", False, "Permit short entries."),
        "atr_period": ParamSpec("integer", 14, "ATR lookback.", min=2, max=100, group="risk"),
        "atr_stop_mult": ParamSpec("number", 2.5, "Hard stop in ATRs (0 disables).",
                                   min=0.0, max=20.0, group="risk"),
        "high_vol_stop_mult": ParamSpec("number", 4.0,
                                        "ATR stop multiple for HIGH_VOL-regime breakouts.",
                                        min=0.0, max=30.0, group="risk"),
        "trailing_atr_mult": ParamSpec("number", 3.5, "Trailing stop in ATRs (0 disables).",
                                       min=0.0, max=20.0, group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 disables).",
                                      min=0, max=100_000, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            adx_trend_min=30.0, er_trend_min=0.45, high_vol_pct=75.0,
            trade_trending=True, trade_ranging=False, trade_high_vol=False, allow_short=False,
            atr_stop_mult=3.0, trailing_atr_mult=5.0,
            sizing_method="volatility_adjusted", target_volatility_pct=1.3,
            max_position_size_pct=12.0,
        ),
        "balanced": preset(
            adx_trend_min=25.0, er_trend_min=0.35, high_vol_pct=80.0,
            trade_trending=True, trade_ranging=True, trade_high_vol=False, allow_short=False,
            atr_stop_mult=2.5, trailing_atr_mult=3.5,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.0, max_position_size_pct=18.0,
        ),
        "aggressive": preset(
            adx_trend_min=20.0, er_trend_min=0.25, high_vol_pct=88.0,
            trade_trending=True, trade_ranging=True, trade_high_vol=True, allow_short=True,
            atr_stop_mult=2.0, trailing_atr_mult=3.0,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.5, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Classifies the market regime each bar (trend strength, efficiency ratio, MA slope, "
            "volatility percentile) and switches between a trend-breakout sub-model, a "
            "mean-reversion sub-model, or standing aside."
        ),
        logic=(
            "Regime from the benchmark (or the instrument itself if no benchmark): HIGH_VOL when "
            "realised-vol percentile >= high_vol_pct; else TRENDING when ADX >= adx_trend_min and "
            "efficiency ratio >= er_trend_min (direction = MA slope sign); else RANGING. "
            "TRENDING -> Donchian breakout of breakout_period in the trend direction, exit on the "
            "breakout_exit_period opposite channel. RANGING -> enter when |Z(mr_lookback)| >= "
            "mr_entry_z against the deviation, exit when |Z| <= mr_exit_z. HIGH_VOL -> optional "
            "wider-stop breakout. All positions also honour an ATR hard stop fixed at entry, an "
            "optional ATR trailing stop, a max holding period, and (optional) an exit on regime "
            "flip."
        ),
        timeframe="day / 60minute",
        market_types=["NSE equities", "index & stock futures"],
        supports_long=True, supports_short=True, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="High", time_horizon="Swing / Positional",
        risks=[
            "Regime labels lag and thrash around their thresholds, causing model churn.",
            "Switching models locks in losses from the previous model at the worst time.",
            "It is a behaviour switch, not a diversified capital allocator — single-model risk "
            "at any moment.",
        ],
        best_for="One instrument or a small book where trend and range phases clearly alternate.",
        warning="Adaptive switching adds parameters and lag; it is not a substitute for "
                "diversification.",
        required_data=[
            "OHLCV bars per instrument, at least vol_percentile_lookback/3 + the longest sub-model "
            "lookback",
            "the benchmark symbol in the stream if benchmark_symbol is set",
        ],
        example=(
            "On daily bars with no benchmark: INFY's ADX is 31 and efficiency ratio 0.5 with a "
            "rising 50-DMA -> TRENDING up -> a long is taken on a 20-day high break, trailed by "
            "3.5x ATR, and cut if the regime turns to RANGING. Mechanics only."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._st: dict[str, _St] = {}
        self._open: dict[str, _OpenPos] = {}

    def _state(self, sym: str) -> _St:
        s = self._st.get(sym)
        if s is None:
            s = _St()
            self._st[sym] = s
        return s

    def _regime(self, sym: str) -> tuple[str, int]:
        """(regime, trend_dir) — trend_dir is +1/-1/0."""
        buf = self._buffers.get(sym)
        if buf is None:
            return "RANGING", 0
        closes = list(buf.closes)
        highs = list(buf.highs)
        lows = list(buf.lows)
        st = self._st.get(sym)
        if len(closes) < max(int(self.p["adx_period"]), int(self.p["slope_ma_period"]),
                             int(self.p["er_period"])) + int(self.p["slope_lookback"]) + 2:
            return "RANGING", 0

        rv = rolling_volatility(closes, int(self.p["vol_lookback"]))
        if (rv is not None and st is not None and len(st.vol_hist) >= 20
                and _pctile(st.vol_hist, rv) >= float(self.p["high_vol_pct"])):
            return "HIGH_VOL", 0

        a = adx(highs, lows, closes, int(self.p["adx_period"]))
        er = _efficiency_ratio(closes, int(self.p["er_period"]))
        slk = int(self.p["slope_lookback"])
        ma_now = self._ma(closes, int(self.p["slope_ma_period"]), "ema")
        ma_prev = self._ma(closes[:-slk], int(self.p["slope_ma_period"]), "ema")
        slope = ((ma_now - ma_prev) / ma_prev) if (ma_now and ma_prev) else 0.0
        trend_dir = 1 if slope > 0 else (-1 if slope < 0 else 0)

        if (a is not None and a >= float(self.p["adx_trend_min"])
                and er >= float(self.p["er_trend_min"]) and trend_dir != 0):
            return "TRENDING", trend_dir
        return "RANGING", 0

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        st = self._state(sym)
        st.seen += 1
        idx = st.seen

        closes = list(buf.closes)
        rv = rolling_volatility(closes, int(self.p["vol_lookback"]))
        if rv is not None:
            st.vol_hist.append(rv)

        bench = str(self.p["benchmark_symbol"]).strip()
        if bench and sym == bench:
            return  # benchmark only feeds regime, never trades

        need = int(self.p["vol_percentile_lookback"]) // 3 + max(
            int(self.p["breakout_period"]), int(self.p["mr_lookback"]),
            int(self.p["atr_period"])) + 5
        if len(closes) < need:
            return
        highs = list(buf.highs)
        lows = list(buf.lows)
        atr_now = atr(highs, lows, closes, int(self.p["atr_period"]))
        if atr_now is None or atr_now <= 0:
            return

        regime, tdir = self._regime(bench if bench in self._buffers else sym)
        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            pos.extreme = max(pos.extreme, price) if pos.side == "long" else min(pos.extreme, price)
            if self._should_exit(sym, pos, price, idx, regime, highs, lows, closes):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if regime == "TRENDING" and self.p["trade_trending"]:
            bp = int(self.p["breakout_period"])
            hi = max(highs[-(bp + 1):-1])
            lo = min(lows[-(bp + 1):-1])
            if tdir > 0 and price > hi:
                self._enter(sym, "long", "trend", price, atr_now, idx)
            elif self.p["allow_short"] and tdir < 0 and price < lo:
                self._enter(sym, "short", "trend", price, atr_now, idx)
        elif regime == "RANGING" and self.p["trade_ranging"]:
            z = zscore(closes, int(self.p["mr_lookback"]))
            if z is not None and abs(z) >= float(self.p["mr_entry_z"]):
                if z < 0:
                    self._enter(sym, "long", "meanrev", price, atr_now, idx)
                elif self.p["allow_short"]:
                    self._enter(sym, "short", "meanrev", price, atr_now, idx)
        elif regime == "HIGH_VOL" and self.p["trade_high_vol"]:
            bp = int(self.p["breakout_period"])
            hi = max(highs[-(bp + 1):-1])
            lo = min(lows[-(bp + 1):-1])
            if price > hi:
                self._enter(sym, "long", "breakout", price, atr_now, idx)
            elif self.p["allow_short"] and price < lo:
                self._enter(sym, "short", "breakout", price, atr_now, idx)

    # --- entry / exit ------------------------------------------

    def _enter(self, sym: str, side: str, model: str, price: float, atr_now: float, idx: int) -> None:
        if side == "long" and not self.long_entries_allowed():
            return
        mult = (float(self.p["high_vol_stop_mult"]) if model == "breakout"
                else float(self.p["atr_stop_mult"]))
        stop_dist = mult * atr_now or price * 0.02
        qty = self.size_position(price, stop_distance=stop_dist, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _OpenPos(side=side, model=model, entry_price=price, entry_index=idx,
                                   entry_atr=atr_now, extreme=price)

    def _should_exit(
        self, sym: str, pos: _OpenPos, price: float, idx: int, regime: str,
        highs: list[float], lows: list[float], closes: list[float],
    ) -> bool:
        mult = (float(self.p["high_vol_stop_mult"]) if pos.model == "breakout"
                else float(self.p["atr_stop_mult"]))
        hard = mult * pos.entry_atr
        trail = float(self.p["trailing_atr_mult"]) * pos.entry_atr
        if pos.side == "long":
            if hard and price <= pos.entry_price - hard:
                return True
            if trail and price <= pos.extreme - trail:
                return True
        else:
            if hard and price >= pos.entry_price + hard:
                return True
            if trail and price >= pos.extreme + trail:
                return True

        if pos.model == "trend":
            xp = int(self.p["breakout_exit_period"])
            if pos.side == "long" and price < min(lows[-(xp + 1):-1]):
                return True
            if pos.side == "short" and price > max(highs[-(xp + 1):-1]):
                return True
            if self.p["exit_on_regime_flip"] and regime == "RANGING":
                return True
        elif pos.model == "meanrev":
            z = zscore(closes, int(self.p["mr_lookback"]))
            if z is not None and abs(z) <= float(self.p["mr_exit_z"]):
                return True
            if self.p["exit_on_regime_flip"] and regime == "TRENDING":
                return True

        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and idx - pos.entry_index >= max_hold)

"""Elder Force Index — trade the trend, time the entry on a Force Index dip.

After Dr Alexander Elder's "Trading for a Living": Force Index =
volume x (close - previous close), smoothed. The 13-EMA sign tells you
which side controls the market; a brief flip of the 2-EMA against the
trend marks the pullback to buy (or the bounce to sell). Trend is the
slope of a 13-EMA of price.

Not guaranteed profitable. Volume-price oscillators still whipsaw in
range-bound markets; validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import _ema_series as ema_series  # noqa: PLC2701
from app.strategies.indicators import atr, ema
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _Open:
    side: str
    entry: float
    stop: float
    entry_index: int
    risk: float


class ForceIndexStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "elder-force-index"
    NAME: ClassVar[str] = "Elder Force Index"
    CATEGORY: ClassVar[str] = "Momentum"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 25
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 45

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "trend_ema": ParamSpec("integer", 13, "EMA of price whose slope defines the trend.",
                               min=3, max=100),
        "trend_slope_bars": ParamSpec("integer", 3, "Bars over which the trend slope is measured.",
                                      min=1, max=20),
        "fi_fast": ParamSpec("integer", 2, "Short Force Index EMA — the entry-timing signal.",
                             min=1, max=20),
        "fi_slow": ParamSpec("integer", 13, "Long Force Index EMA — who controls the market.",
                             min=3, max=60),
        "arm_expiry_bars": ParamSpec("integer", 3, "Bars the break-of-prior-bar trigger stays live.",
                                     min=1, max=20),
        "allow_short": ParamSpec("boolean", False, "Also trade the short side in a downtrend."),
        "exit_on_fi_slow_flip": ParamSpec("boolean", True, "Exit when the 13-EMA Force Index crosses "
                                          "its centreline against the position.", group="risk"),
        "atr_period": ParamSpec("integer", 14, "ATR period for the fallback stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 0.0, "If > 0, widen the stop to max(prior-bar extreme, "
                                   "this x ATR).", min=0.0, max=10.0, group="risk"),
        "trailing_atr_mult": ParamSpec("number", 0.0, "Trailing stop in ATRs (0 disables).",
                                       min=0.0, max=10.0, group="risk"),
        "take_profit_r": ParamSpec("number", 0.0, "Take profit at this multiple of initial risk "
                                   "(0 disables).", min=0.0, max=20.0, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(trend_ema=21, trend_slope_bars=5, allow_short=False,
                               exit_on_fi_slow_flip=True, atr_stop_mult=1.5, trailing_atr_mult=3.0,
                               take_profit_r=2.0, product="CNC", sizing_method="risk_per_trade",
                               risk_per_trade_pct=0.5, max_position_size_pct=15.0),
        "balanced": preset(trend_ema=13, trend_slope_bars=3, allow_short=False,
                           exit_on_fi_slow_flip=True, atr_stop_mult=0.0, trailing_atr_mult=0.0,
                           take_profit_r=2.0, product="MIS", sizing_method="risk_per_trade",
                           risk_per_trade_pct=1.0, max_position_size_pct=20.0),
        "aggressive": preset(trend_ema=9, trend_slope_bars=2, allow_short=True, arm_expiry_bars=2,
                             exit_on_fi_slow_flip=False, atr_stop_mult=0.0, trailing_atr_mult=2.5,
                             take_profit_r=0.0, product="MIS", sizing_method="risk_per_trade",
                             risk_per_trade_pct=1.5, max_position_size_pct=25.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Buys in an uptrend when the 2-EMA Force Index dips below zero (the pullback) "
                     "and the next bar breaks the prior high; mirror for shorts. Exits on the "
                     "trend flipping, an optional 13-EMA Force Index centreline flip, and the "
                     "usual stops."),
        logic=("Force Index = volume x (close - prev close). trend = sign of EMA(trend_ema) now vs "
               "trend_slope_bars ago. In an uptrend, when EMA(fi_fast) of Force Index goes <= 0, arm "
               "a stop-entry at the prior bar's high for arm_expiry_bars; on the break enter long "
               "with the stop at the prior bar's low (optionally widened to atr_stop_mult x ATR). "
               "Exit on: stop, optional ATR trailing stop, optional take-profit, the trend flipping, "
               "or (if exit_on_fi_slow_flip) EMA(fi_slow) of Force Index crossing its centreline "
               "against the position."),
        timeframe="day / 60minute / 15minute",
        market_types=["NSE equities", "liquid futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Intraday / Swing",
        risks=["Force Index needs real volume; illiquid names give noisy signals.",
               "The trend-slope filter lags, so the last pullback of a trend still triggers.",
               "Gaps through the prior-bar stop cause larger losses than modelled."],
        best_for="Pullback entries in a volume-confirmed trend.",
        warning="A volume-price oscillator; only as good as the volume data behind it.",
        required_data=["OHLCV bars per instrument, at least fi_slow + trend_ema + a few bars"],
        example=("On daily RELIANCE bars in an uptrend: the 2-EMA Force Index prints -X after a "
                 "green run, the next bar takes out the prior high -> go long with the stop at that "
                 "bar's low. Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._armed: dict[str, tuple[str, float, float, int]] = {}  # side, trigger, stop, idx
        self._open: dict[str, _Open] = {}
        self._seen: dict[str, int] = {}

    def _force_emas(self, closes: list[float], vols: list[float]) -> tuple[float, float] | None:
        if len(closes) < max(int(self.p["fi_slow"]), int(self.p["fi_fast"])) + 2:
            return None
        raw = [vols[i] * (closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        fast = ema_series(raw, int(self.p["fi_fast"]))
        slow = ema_series(raw, int(self.p["fi_slow"]))
        if not fast or not slow:
            return None
        px = closes[-1] or 1.0
        return fast[-1] / px, slow[-1] / px

    def _trend(self, closes: list[float]) -> int:
        n, k = int(self.p["trend_ema"]), int(self.p["trend_slope_bars"])
        now = ema(closes, n)
        past = ema(closes[: len(closes) - k], n) if len(closes) > n + k else None
        if now is None or past is None:
            return 0
        return 1 if now > past else -1 if now < past else 0

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        closes, vols = list(buf.closes), list(buf.volumes)
        fe = self._force_emas(closes, vols)
        if fe is None:
            return
        fi_fast, fi_slow = fe
        trend = self._trend(closes)
        a = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        pos = self._open.get(sym)

        if pos is not None:
            if self._should_exit(pos, bar, trend, fi_slow, a):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
                self._armed.pop(sym, None)
            return

        armed = self._armed.get(sym)
        if armed is not None:
            side, trig, stop, ai = armed
            if idx - ai > int(self.p["arm_expiry_bars"]):
                self._armed.pop(sym, None)
            elif side == "long" and bar.high >= trig:
                self._enter(sym, "long", max(closes[-1], trig), stop, idx, a)
                return
            elif side == "short" and bar.low <= trig:
                self._enter(sym, "short", min(closes[-1], trig), stop, idx, a)
                return

        prev = buf.bars[-2]
        if trend > 0 and fi_fast <= 0 and self.long_entries_allowed():
            self._armed[sym] = ("long", float(bar.high), float(prev.low), idx)
        elif trend < 0 and self.p["allow_short"] and fi_fast >= 0:
            self._armed[sym] = ("short", float(bar.low), float(prev.high), idx)

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

    def _should_exit(self, pos: _Open, bar: Bar, trend: int, fi_slow: float,
                     a: float | None) -> bool:
        trail = float(self.p["trailing_atr_mult"])
        price = float(bar.close)
        if trail > 0 and a:
            if pos.side == "long":
                pos.stop = max(pos.stop, price - trail * a)
            else:
                pos.stop = min(pos.stop, price + trail * a)
        flip = bool(self.p["exit_on_fi_slow_flip"])
        tp = float(self.p["take_profit_r"])
        if pos.side == "long":
            if bar.low <= pos.stop or trend < 0 or (flip and fi_slow < 0):
                return True
            return tp > 0 and bar.high >= pos.entry + tp * pos.risk
        if bar.high >= pos.stop or trend > 0 or (flip and fi_slow > 0):
            return True
        return tp > 0 and bar.low <= pos.entry - tp * pos.risk

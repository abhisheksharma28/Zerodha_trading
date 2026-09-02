"""Weapon Candle — EMA9 reclaim + MACD confirmation, break of the signal bar.

The "weapon candle" is the bar that flips a stock back across its 9-EMA with
MACD momentum agreeing. Entry is a stop through that bar's extreme; the
stop-loss is the bar's opposite extreme.

* ``classic`` mode: the pattern only.
* ``enhanced`` mode: the pattern plus price-based confirmations (session
  VWAP alignment, volume expansion, an RSI regime band, MACD-histogram
  strength) rolled into a 0-100 ``alpha score``; a trade is taken only
  above ``alpha_score_min``.

Order-flow confirmation (delta / CVD / stacked imbalance) as described for
this strategy needs true tick data and is a live-only extension — it is NOT
part of the backtest and is not simulated here.

Not guaranteed profitable. A single-bar reversal pattern produces many
false signals in choppy conditions; validate out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, ema, macd, rsi, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset

# bar_dt() already returns IST wall-clock, so a naive time compares correctly.
_SQUARE_OFF = dt_time(15, 20)


@dataclass
class _Armed:
    side: str  # "long" | "short"
    weapon_high: float
    weapon_low: float
    armed_index: int
    alpha_score: float


@dataclass
class _OpenPos:
    side: str
    entry_price: float
    entry_index: int
    initial_risk: float  # per-share stop distance at entry
    stop_price: float


class WeaponCandleStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "weapon-candle"
    NAME: ClassVar[str] = "Weapon Candle"
    CATEGORY: ClassVar[str] = "Momentum"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m", "30m", "15m")
    MIN_BARS_REQUIRED: ClassVar[int] = 45

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "mode": ParamSpec("enum", "classic", "classic = pattern only; enhanced = pattern + "
                          "price-confirmation alpha score.", choices=("classic", "enhanced")),
        "ema_period": ParamSpec("integer", 9, "EMA the weapon candle must reclaim.", min=2, max=100),
        "macd_fast": ParamSpec("integer", 12, "MACD fast EMA.", min=2, max=100),
        "macd_slow": ParamSpec("integer", 26, "MACD slow EMA.", min=3, max=200),
        "macd_signal": ParamSpec("integer", 9, "MACD signal EMA.", min=2, max=100),
        "require_prev_below": ParamSpec("boolean", True,
                                        "Require the prior bar to open AND close on the wrong side "
                                        "of the EMA before the weapon candle."),
        "arm_expiry_bars": ParamSpec("integer", 3,
                                     "Bars the break-of-weapon-candle trigger stays live.",
                                     min=1, max=20),
        "allow_short": ParamSpec("boolean", False, "Permit bearish weapon candles."),
        "atr_period": ParamSpec("integer", 14, "ATR lookback for the fallback stop.",
                                min=2, max=100, group="risk"),
        "atr_stop_mult": ParamSpec("number", 0.0,
                                   "If > 0, use max(weapon-candle stop, this x ATR) as the stop.",
                                   min=0.0, max=20.0, group="risk"),
        "trailing_atr_mult": ParamSpec("number", 0.0, "Trailing stop in ATRs (0 disables).",
                                       min=0.0, max=20.0, group="risk"),
        "take_profit_r": ParamSpec("number", 0.0, "Take profit at this multiple of initial risk "
                                   "(0 disables).", min=0.0, max=50.0, group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 disables).",
                                      min=0, max=100_000, group="risk"),
        # --- enhanced-mode confirmations ---
        "alpha_score_min": ParamSpec("number", 60.0, "Minimum alpha score (enhanced mode).",
                                     min=0.0, max=100.0, group="filter"),
        "use_vwap_align": ParamSpec("boolean", True,
                                    "Enhanced: long needs close > session VWAP (intraday only).",
                                    group="filter"),
        "use_volume_expansion": ParamSpec("boolean", True,
                                          "Enhanced: weapon-candle volume > mult x 20-bar average.",
                                          group="filter"),
        "vol_expansion_mult": ParamSpec("number", 1.3, "Volume-expansion multiple.",
                                        min=1.0, max=10.0, group="filter"),
        "rsi_period": ParamSpec("integer", 14, "RSI lookback (enhanced regime band).",
                                min=2, max=100, group="filter"),
        "rsi_long_band": ParamSpec("number", 45.0,
                                   "Enhanced: long needs RSI >= this (short needs RSI <= 100-this).",
                                   min=1.0, max=99.0, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            mode="enhanced", alpha_score_min=75.0, require_prev_below=True, allow_short=False,
            atr_stop_mult=1.5, trailing_atr_mult=3.0, take_profit_r=2.0,
            use_vwap_align=True, use_volume_expansion=True, vol_expansion_mult=1.5,
            sizing_method="risk_per_trade", risk_per_trade_pct=0.5, max_position_size_pct=10.0,
        ),
        "balanced": preset(
            mode="enhanced", alpha_score_min=60.0, require_prev_below=True, allow_short=False,
            atr_stop_mult=0.0, trailing_atr_mult=0.0, take_profit_r=2.0,
            use_vwap_align=True, use_volume_expansion=True, vol_expansion_mult=1.3,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.0, max_position_size_pct=20.0,
        ),
        "aggressive": preset(
            mode="classic", require_prev_below=False, allow_short=True, arm_expiry_bars=2,
            atr_stop_mult=0.0, trailing_atr_mult=2.5, take_profit_r=0.0,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.5, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Enters on a break of the bar that reclaims the 9-EMA with MACD momentum agreeing; "
            "the stop is that bar's opposite extreme. Optional enhanced mode adds price-based "
            "confirmations as a 0-100 alpha score."
        ),
        logic=(
            "Detect a 'weapon candle': close back across EMA(ema_period) with MACD histogram on "
            "the same side (and, if require_prev_below, the prior bar fully on the wrong side). "
            "Arm a stop-entry at its high (long) / low (short) for arm_expiry_bars. On the break, "
            "enter; stop = weapon-candle low/high (optionally widened to atr_stop_mult x ATR). "
            "Exits: stop, optional ATR trailing stop, optional take-profit at take_profit_r x "
            "initial risk, optional max holding period, and an end-of-day square-off intraday. In "
            "enhanced mode the signal must also score >= alpha_score_min from VWAP alignment, "
            "volume expansion, an RSI regime band and MACD-histogram strength."
        ),
        timeframe="15minute / 30minute / 60minute / day",
        market_types=["NSE equities", "liquid futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Intraday / Swing",
        risks=[
            "Single-bar reversal patterns whipsaw badly in choppy, low-trend conditions.",
            "Gap moves through the weapon-candle stop cause larger-than-modelled losses.",
            "Enhanced-mode order-flow confirmation is live-only and absent from the backtest.",
        ],
        best_for="Intraday and short-swing continuation entries after an EMA reclaim.",
        warning="A single-candle pattern generates frequent false signals; confirmation matters.",
        required_data=["OHLCV bars per instrument, at least macd_slow + macd_signal + a few bars"],
        example=(
            "On 15-minute INFY bars: a candle closes back above the 9-EMA with MACD histogram > 0 "
            "after the prior candle was entirely below it. A buy-stop is placed at that candle's "
            "high for 3 bars; if hit, the stop-loss sits at the candle's low. Mechanics only."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._armed: dict[str, _Armed] = {}
        self._open: dict[str, _OpenPos] = {}
        self._seen: dict[str, int] = {}
        self._session_day: dict[str, Any] = {}
        self._vwap_num: dict[str, float] = {}
        self._vwap_den: dict[str, float] = {}

    # --- helpers ---------------------------------------------------

    def _session_vwap(self, bar: Bar, sym: str) -> float | None:
        dt = self.bar_dt(bar)
        day = dt.date()
        if self._session_day.get(sym) != day:
            self._session_day[sym] = day
            self._vwap_num[sym] = 0.0
            self._vwap_den[sym] = 0.0
        tp = (bar.high + bar.low + bar.close) / 3.0
        v = float(bar.volume or 0.0)
        self._vwap_num[sym] += tp * v
        self._vwap_den[sym] += v
        return self._vwap_num[sym] / self._vwap_den[sym] if self._vwap_den[sym] > 0 else None

    def _alpha_score(
        self, side: str, buf, close: float, vwap: float | None, hist: float, hist_ref: float,
    ) -> float:
        score = 40.0
        if self.p["use_vwap_align"] and vwap is not None:
            if (side == "long" and close > vwap) or (side == "short" and close < vwap):
                score += 15.0
        elif not self.p["use_vwap_align"]:
            score += 7.0
        if self.p["use_volume_expansion"]:
            avg = sma(list(buf.volumes), 20)
            if avg and avg > 0 and buf.volumes[-1] >= float(self.p["vol_expansion_mult"]) * avg:
                score += 15.0
        else:
            score += 7.0
        r = rsi(list(buf.closes), int(self.p["rsi_period"]))
        band = float(self.p["rsi_long_band"])
        if r is not None and ((side == "long" and r >= band) or (side == "short" and r <= 100 - band)):
            score += 15.0
        if hist_ref > 0 and abs(hist) >= 0.5 * hist_ref:
            score += 15.0
        return min(100.0, score)

    # --- main ----------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        vwap = self._session_vwap(bar, sym)

        closes = list(buf.closes)
        n = max(int(self.p["macd_slow"]) + int(self.p["macd_signal"]), int(self.p["ema_period"])) + 2
        if len(closes) < n:
            return

        ema_now = ema(closes, int(self.p["ema_period"]))
        ema_prev = ema(closes[:-1], int(self.p["ema_period"]))
        m = macd(closes, int(self.p["macd_fast"]), int(self.p["macd_slow"]),
                 int(self.p["macd_signal"]))
        if ema_now is None or ema_prev is None or m is None:
            return
        _macd_line, _sig, hist = m
        price = closes[-1]
        pos = self._open.get(sym)

        # --- manage an open position ---
        if pos is not None:
            if self._exit(sym, pos, bar, idx):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
                self._armed.pop(sym, None)
            return

        # --- trigger a pending armed signal ---
        armed = self._armed.get(sym)
        if armed is not None:
            if idx - armed.armed_index > int(self.p["arm_expiry_bars"]):
                self._armed.pop(sym, None)
            elif armed.side == "long" and bar.high >= armed.weapon_high:
                self._enter(sym, armed, entry=max(price, armed.weapon_high), idx=idx)
                return
            elif armed.side == "short" and bar.low <= armed.weapon_low:
                self._enter(sym, armed, entry=min(price, armed.weapon_low), idx=idx)
                return

        # --- detect a fresh weapon candle ---
        prev = buf.bars[-2]
        hist_ref = max(abs(hist), 1e-9)
        long_ok = (
            price > ema_now and hist > 0
            and (not self.p["require_prev_below"] or (prev.open < ema_prev and prev.close < ema_prev))
        )
        short_ok = (
            self.p["allow_short"] and price < ema_now and hist < 0
            and (not self.p["require_prev_below"] or (prev.open > ema_prev and prev.close > ema_prev))
        )
        if not (long_ok or short_ok):
            return
        side = "long" if long_ok else "short"
        score = self._alpha_score(side, buf, price, vwap, hist, hist_ref)
        if self.p["mode"] == "enhanced" and score < float(self.p["alpha_score_min"]):
            return
        if side == "long" and not self.long_entries_allowed():
            return
        self._armed[sym] = _Armed(side=side, weapon_high=float(bar.high), weapon_low=float(bar.low),
                                  armed_index=idx, alpha_score=score)

    # --- entry / exit -------------------------------------------

    def _enter(self, sym: str, armed: _Armed, *, entry: float, idx: int) -> None:
        buf = self._buffers[sym]
        raw_stop = armed.weapon_low if armed.side == "long" else armed.weapon_high
        risk = abs(entry - raw_stop)
        atr_mult = float(self.p["atr_stop_mult"])
        if atr_mult > 0:
            a = atr(list(buf.highs), list(buf.lows), list(buf.closes), int(self.p["atr_period"]))
            if a:
                risk = max(risk, atr_mult * a)
        if risk <= 0:
            risk = entry * 0.01
        stop_price = entry - risk if armed.side == "long" else entry + risk
        qty = self.size_position(entry, stop_distance=risk, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if armed.side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _OpenPos(side=armed.side, entry_price=entry, entry_index=idx,
                                   initial_risk=risk, stop_price=stop_price)
        self._armed.pop(sym, None)

    def _exit(self, sym: str, pos: _OpenPos, bar: Bar, idx: int) -> bool:
        price = float(bar.close)
        # intraday square-off
        if self.p["product"] == "MIS" and self.bar_dt(bar).time() >= _SQUARE_OFF:
            return True
        trail = float(self.p["trailing_atr_mult"])
        if trail > 0:
            buf = self._buffers[sym]
            a = atr(list(buf.highs), list(buf.lows), list(buf.closes), int(self.p["atr_period"]))
            if a:
                if pos.side == "long":
                    pos.stop_price = max(pos.stop_price, price - trail * a)
                else:
                    pos.stop_price = min(pos.stop_price, price + trail * a)
        if pos.side == "long":
            if bar.low <= pos.stop_price:
                return True
            tp = float(self.p["take_profit_r"])
            if tp > 0 and bar.high >= pos.entry_price + tp * pos.initial_risk:
                return True
        else:
            if bar.high >= pos.stop_price:
                return True
            tp = float(self.p["take_profit_r"])
            if tp > 0 and bar.low <= pos.entry_price - tp * pos.initial_risk:
                return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and idx - pos.entry_index >= max_hold)

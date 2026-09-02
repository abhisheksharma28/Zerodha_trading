"""Volatility Regime — classify each instrument's realised-volatility regime
and adapt.

Each bar the strategy places current realised volatility on a percentile of
its own recent history (LOW / NORMAL / HIGH / EXTREME) and separately tracks
range compression (Bollinger-band width percentile). It then:

* takes a **compression breakout** — a range break while volatility expands
  out of a compressed state — in the breakout direction;
* **trend-follows** in LOW/NORMAL volatility (price vs a moving average);
* **stops taking new entries in EXTREME volatility** (optional), and sizes
  positions down as volatility rises when volatility-adjusted sizing is on.

An optional India-VIX-style symbol, if present in the data stream, can veto
new entries when its own percentile is extreme.

Not guaranteed profitable. Volatility-timing edges are unstable and
regime labels lag; validate out-of-sample.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, bollinger, rolling_volatility
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


def _pctile(hist: deque[float], value: float) -> float:
    if not hist:
        return 50.0
    return 100.0 * sum(1 for h in hist if h <= value) / len(hist)


@dataclass
class _OpenPos:
    side: str
    entry_price: float
    entry_index: int
    entry_atr: float
    extreme: float
    reason: str


@dataclass
class _State:
    vol_hist: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    bw_hist: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    seen: int = 0


class VolatilityRegimeStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "volatility-regime"
    NAME: ClassVar[str] = "Volatility Regime"
    CATEGORY: ClassVar[str] = "Volatility"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d", "60m")
    MIN_BARS_REQUIRED: ClassVar[int] = 80

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "mode": ParamSpec("enum", "breakout_and_trend",
                          "Which entries are allowed.",
                          choices=("breakout_and_trend", "breakout_only", "trend_only")),
        "vol_lookback": ParamSpec("integer", 20, "Realised-volatility window.", min=5, max=200),
        "vol_percentile_lookback": ParamSpec("integer", 252,
                                             "History used to rank current volatility.",
                                             min=30, max=1000),
        "low_pct": ParamSpec("number", 30.0, "Vol percentile below this = LOW regime.",
                             min=1.0, max=99.0),
        "high_pct": ParamSpec("number", 70.0, "Vol percentile above this = HIGH regime.",
                              min=1.0, max=99.0),
        "extreme_pct": ParamSpec("number", 90.0, "Vol percentile above this = EXTREME regime.",
                                 min=1.0, max=100.0),
        "no_trade_in_extreme": ParamSpec("boolean", True, "Block new entries in EXTREME vol.",
                                         group="filter"),
        "expansion_mult": ParamSpec("number", 1.4,
                                    "current vol / vol[-expansion_ref] above this = 'expanding'.",
                                    min=1.0, max=10.0),
        "expansion_ref": ParamSpec("integer", 10, "Bars back for the expansion ratio.",
                                   min=1, max=100),
        "compression_pctile_max": ParamSpec("number", 25.0,
                                            "Bollinger-width percentile below this = compressed.",
                                            min=1.0, max=99.0),
        "breakout_period": ParamSpec("integer", 20, "Range lookback for the breakout entry.",
                                     min=3, max=300),
        "bollinger_period": ParamSpec("integer", 20, "Bollinger lookback for band width.",
                                      min=5, max=200),
        "trend_ma_period": ParamSpec("integer", 50, "MA for the trend-follow entry.",
                                     min=3, max=400),
        "trend_ma_type": ParamSpec("enum", "ema", "MA type.", choices=("sma", "ema")),
        "allow_short": ParamSpec("boolean", False, "Permit short entries."),
        "atr_period": ParamSpec("integer", 14, "ATR lookback.", min=2, max=100, group="risk"),
        "atr_stop_mult": ParamSpec("number", 2.5, "Hard stop in ATRs (0 disables).",
                                   min=0.0, max=20.0, group="risk"),
        "trailing_atr_mult": ParamSpec("number", 4.0, "Trailing stop in ATRs (0 disables).",
                                       min=0.0, max=20.0, group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 disables).",
                                      min=0, max=100_000, group="risk"),
        "vix_symbol": ParamSpec("string", "",
                                "Optional India-VIX-style tradingsymbol in the stream; blank = off.",
                                group="filter"),
        "vix_veto_pct": ParamSpec("number", 85.0,
                                  "If vix_symbol's own percentile exceeds this, block new entries.",
                                  min=1.0, max=100.0, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            mode="trend_only", allow_short=False, no_trade_in_extreme=True,
            trend_ma_period=100, atr_stop_mult=3.0, trailing_atr_mult=5.0,
            sizing_method="volatility_adjusted", target_volatility_pct=1.2,
            max_position_size_pct=10.0,
        ),
        "balanced": preset(
            mode="breakout_and_trend", allow_short=False, no_trade_in_extreme=True,
            breakout_period=20, trend_ma_period=50, atr_stop_mult=2.5, trailing_atr_mult=4.0,
            sizing_method="volatility_adjusted", target_volatility_pct=1.8,
            max_position_size_pct=18.0,
        ),
        "aggressive": preset(
            mode="breakout_only", allow_short=True, no_trade_in_extreme=False,
            breakout_period=15, expansion_mult=1.3, compression_pctile_max=35.0,
            atr_stop_mult=2.0, trailing_atr_mult=3.0,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.25, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Ranks each instrument's realised volatility on its own history, trades range "
            "breakouts out of compressed low-vol states and trend-follows in normal vol, and "
            "stands aside in extreme volatility."
        ),
        logic=(
            "Each bar: realised vol over vol_lookback -> percentile over vol_percentile_lookback "
            "-> regime (LOW/NORMAL/HIGH/EXTREME). Bollinger-band width -> percentile -> "
            "'compressed' if below compression_pctile_max. Entries (subject to mode): a "
            "compression breakout = price breaks the breakout_period range while vol is expanding "
            "(current / expansion_ref bars ago > expansion_mult); a trend entry = price crosses "
            "trend_ma in LOW/NORMAL vol. New entries are blocked in EXTREME vol (optional) and "
            "when an optional VIX symbol's percentile is extreme. Exits: ATR hard stop fixed at "
            "entry, optional ATR trailing stop, optional max holding period."
        ),
        timeframe="day / 60minute",
        market_types=["NSE equities", "index & stock futures"],
        supports_long=True, supports_short=True, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="High", time_horizon="Swing / Positional",
        risks=[
            "Volatility regime labels lag and whipsaw around the bucket edges.",
            "Compression breakouts fail often (false starts) in range-bound markets.",
            "A gap through the ATR stop in a volatility spike causes an outsized loss.",
        ],
        best_for="Swing trading instruments that alternate between quiet coiling and expansion.",
        warning="Volatility-timing edges are unstable; treat regime labels as approximate.",
        required_data=[
            "OHLCV bars per instrument, at least vol_percentile_lookback + vol_lookback bars",
            "the VIX symbol in the stream if vix_symbol is set",
        ],
        example=(
            "On daily bars: NIFTYBEES volatility sits in its 15th percentile and Bollinger width "
            "in its 10th (compressed); price then closes above the 20-day high while 20-day vol "
            "is 1.5x its level 10 days ago -> long, stop 2.5x ATR. Mechanics only."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._st: dict[str, _State] = {}
        self._open: dict[str, _OpenPos] = {}

    def _state(self, sym: str) -> _State:
        s = self._st.get(sym)
        if s is None:
            s = _State()
            self._st[sym] = s
        return s

    def _vix_blocks(self) -> bool:
        vs = str(self.p["vix_symbol"]).strip()
        if not vs:
            return False
        st = self._st.get(vs)
        buf = self._buffers.get(vs)
        if st is None or buf is None or len(buf.closes) < int(self.p["vol_lookback"]) + 1:
            return False  # fail open
        cur = rolling_volatility(list(buf.closes), int(self.p["vol_lookback"]))
        if cur is None:
            return False
        return _pctile(st.vol_hist, cur) >= float(self.p["vix_veto_pct"])

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        st = self._state(sym)
        st.seen += 1
        idx = st.seen

        closes = list(buf.closes)
        vlb = int(self.p["vol_lookback"])
        rv = rolling_volatility(closes, vlb)
        if rv is not None:
            st.vol_hist.append(rv)
        bb = bollinger(closes, int(self.p["bollinger_period"]))
        if bb is not None:
            upper, mid, lower = bb
            if mid:
                st.bw_hist.append((upper - lower) / mid)

        # the VIX symbol only maintains history; it is not traded here
        if sym == str(self.p["vix_symbol"]).strip():
            return

        need = max(int(self.p["vol_percentile_lookback"]) // 4,
                   int(self.p["breakout_period"]), int(self.p["trend_ma_period"]),
                   int(self.p["atr_period"])) + vlb + 2
        if len(closes) < need or rv is None:
            return
        atr_now = atr(list(buf.highs), list(buf.lows), closes, int(self.p["atr_period"]))
        if atr_now is None or atr_now <= 0:
            return

        price = closes[-1]
        pos = self._open.get(sym)
        if pos is not None:
            pos.extreme = max(pos.extreme, price) if pos.side == "long" else min(pos.extreme, price)
            if self._should_exit(pos, price, idx):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        vol_pct = _pctile(st.vol_hist, rv)
        regime = (
            "EXTREME" if vol_pct >= float(self.p["extreme_pct"])
            else "HIGH" if vol_pct >= float(self.p["high_pct"])
            else "LOW" if vol_pct <= float(self.p["low_pct"])
            else "NORMAL"
        )
        if regime == "EXTREME" and self.p["no_trade_in_extreme"]:
            return
        if self._vix_blocks():
            return

        mode = self.p["mode"]
        side: str | None = None
        reason = ""

        if mode in ("breakout_and_trend", "breakout_only"):
            eref = int(self.p["expansion_ref"])
            expanding = (
                len(st.vol_hist) > eref
                and st.vol_hist[-1 - eref] > 0
                and rv / st.vol_hist[-1 - eref] >= float(self.p["expansion_mult"])
            )
            compressed = (
                bool(st.bw_hist) and len(st.bw_hist) >= 20
                and _pctile(st.bw_hist, st.bw_hist[-1]) <= float(self.p["compression_pctile_max"])
            )
            bp = int(self.p["breakout_period"])
            highs = list(buf.highs)
            lows = list(buf.lows)
            prior_high = max(highs[-(bp + 1):-1])
            prior_low = min(lows[-(bp + 1):-1])
            if expanding and compressed:
                if price > prior_high:
                    side, reason = "long", "compression_breakout"
                elif self.p["allow_short"] and price < prior_low:
                    side, reason = "short", "compression_breakout"

        if side is None and mode in ("breakout_and_trend", "trend_only") and regime in ("LOW", "NORMAL"):
            ma = self._ma(closes, int(self.p["trend_ma_period"]), self.p["trend_ma_type"])
            ma_prev = self._ma(closes[:-1], int(self.p["trend_ma_period"]), self.p["trend_ma_type"])
            if ma is not None and ma_prev is not None:
                if closes[-2] <= ma_prev < price and price > ma:
                    side, reason = "long", "trend_cross"
                elif self.p["allow_short"] and closes[-2] >= ma_prev > price and price < ma:
                    side, reason = "short", "trend_cross"

        if side is None:
            return
        if side == "long" and not self.long_entries_allowed():
            return
        self._enter(sym, side, price, atr_now, idx, reason)

    # --- entry / exit ------------------------------------------

    def _enter(self, sym: str, side: str, price: float, atr_now: float, idx: int, reason: str) -> None:
        stop_dist = float(self.p["atr_stop_mult"]) * atr_now or price * 0.02
        qty = self.size_position(price, stop_distance=stop_dist, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _OpenPos(side=side, entry_price=price, entry_index=idx,
                                   entry_atr=atr_now, extreme=price, reason=reason)

    def _should_exit(self, pos: _OpenPos, price: float, idx: int) -> bool:
        hard = float(self.p["atr_stop_mult"]) * pos.entry_atr
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
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and idx - pos.entry_index >= max_hold)

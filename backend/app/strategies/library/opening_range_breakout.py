"""Opening Range Breakout (ORB) — intraday NSE breakout strategy.

For each instrument each trading day the strategy measures the opening
range (default 09:15-09:30 IST) high/low, session VWAP and opening volume,
then trades a break of that range with volume confirmation and optional
VWAP / benchmark-trend filters. Hard intraday risk controls apply:
per-side and total trade caps, a max daily loss, a stop / target / trailing
stop, and a forced square-off time after which no position is held.

Not guaranteed profitable. Breakout systems are very sensitive to
transaction costs and false breakouts. Validate out-of-sample with a
realistic Indian cost model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import atr, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


def _parse_hhmm(s: str) -> time:
    hh, mm = s.strip().split(":")
    return time(int(hh), int(mm))


@dataclass
class _DayState:
    day: date
    or_high: float = 0.0
    or_low: float = 0.0
    or_locked: bool = False
    or_volume: float = 0.0
    session_pv: float = 0.0
    session_v: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    realized_pnl: float = 0.0
    open_side: str | None = None
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    extreme: float = 0.0
    bar_count_in_or: int = 0
    or_volumes: list[float] = field(default_factory=list)


class OpeningRangeBreakoutStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "opening-range-breakout"
    NAME: ClassVar[str] = "Opening Range Breakout"
    CATEGORY: ClassVar[str] = "Breakout"
    MIN_INSTRUMENTS: ClassVar[int] = 1

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "opening_range_start": ParamSpec("string", "09:15", "OR window start (HH:MM IST)."),
        "opening_range_end": ParamSpec("string", "09:30", "OR window end (HH:MM IST)."),
        "square_off_time": ParamSpec("string", "15:15", "Force-flat time (HH:MM IST)."),
        "allowed_weekdays": ParamSpec("string", "0,1,2,3,4",
                                      "Weekdays the strategy may trade (Mon=0)."),
        "volume_multiplier": ParamSpec("number", 1.5,
                                       "Breakout bar volume must exceed this * mean OR-bar volume.",
                                       min=0.0, max=50.0, group="filter"),
        "use_vwap_filter": ParamSpec("boolean", True,
                                     "Longs require price > VWAP, shorts price < VWAP.",
                                     group="filter"),
        "market_trend_filter": ParamSpec("boolean", False,
                                         "Require the benchmark to agree with the trade direction.",
                                         group="filter"),
        "atr_period": ParamSpec("integer", 14, "ATR lookback for the ATR stop.", min=2, max=100,
                                group="risk"),
        "atr_stop_mult": ParamSpec("number", 0.0,
                                   "Stop distance in ATRs (0 uses stop_loss_pct instead).",
                                   min=0.0, max=20.0, group="risk"),
        "stop_loss_pct": ParamSpec("number", 0.5, "Stop distance (%) from entry.",
                                   min=0.01, max=50.0, group="risk"),
        "target_pct": ParamSpec("number", 1.0, "Take-profit distance (%) from entry (0 off).",
                                min=0.0, max=100.0, group="risk"),
        "trailing_stop_pct": ParamSpec("number", 0.0, "Trailing stop distance (%) (0 off).",
                                       min=0.0, max=50.0, group="risk"),
        "max_long_trades_per_day": ParamSpec("integer", 1, "Cap on long entries per day.",
                                             min=0, max=50, group="risk"),
        "max_short_trades_per_day": ParamSpec("integer", 1, "Cap on short entries per day.",
                                              min=0, max=50, group="risk"),
        "max_trades_per_day": ParamSpec("integer", 2, "Overall cap on entries per day.",
                                        min=0, max=100, group="risk"),
        "max_daily_loss_pct": ParamSpec("number", 2.0,
                                        "Stop trading for the day after this loss "
                                        "(% of capital_allocation; 0 off).",
                                        min=0.0, max=100.0, group="risk"),
        "allow_short": ParamSpec("boolean", True, "Permit short breakouts."),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product (intraday => MIS).",
                             choices=("MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            opening_range_end="09:45", volume_multiplier=2.0, use_vwap_filter=True,
            market_trend_filter=True, stop_loss_pct=0.4, target_pct=0.8,
            max_long_trades_per_day=1, max_short_trades_per_day=1, max_trades_per_day=1,
            max_daily_loss_pct=1.0, allow_short=False, sizing_method="fixed_capital",
            max_position_size_pct=10.0,
        ),
        "balanced": preset(
            opening_range_end="09:30", volume_multiplier=1.5, use_vwap_filter=True,
            stop_loss_pct=0.5, target_pct=1.0, trailing_stop_pct=0.5,
            max_long_trades_per_day=1, max_short_trades_per_day=1, max_trades_per_day=2,
            max_daily_loss_pct=2.0, allow_short=True, sizing_method="fixed_quantity",
            fixed_quantity=1,
        ),
        "aggressive": preset(
            opening_range_end="09:20", volume_multiplier=1.0, use_vwap_filter=False,
            stop_loss_pct=0.7, target_pct=1.5, trailing_stop_pct=0.6,
            max_long_trades_per_day=2, max_short_trades_per_day=2, max_trades_per_day=4,
            max_daily_loss_pct=3.0, allow_short=True, sizing_method="risk_per_trade",
            risk_per_trade_pct=1.0, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Intraday strategy that trades a break of the first 15-30 minutes' price range on NSE, "
            "with volume confirmation, optional VWAP / benchmark filters, and a hard square-off."
        ),
        logic=(
            "Between opening_range_start and opening_range_end record the high, low, VWAP and "
            "volume of the opening range. After it locks, go long when a bar closes above the OR "
            "high with volume > volume_multiplier * mean OR-bar volume (and price > VWAP / "
            "benchmark up, if those filters are on); mirror for shorts. Manage with a stop "
            "(stop_loss_pct or ATR), optional target and trailing stop, per-side and total daily "
            "trade caps, a max daily loss, and a forced flat at square_off_time."
        ),
        timeframe="1minute / 3minute / 5minute (intraday only)",
        market_types=["NSE equities", "index futures", "liquid F&O names"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=False,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Intraday",
        risks=[
            "False breakouts that immediately reverse through the stop.",
            "Transaction costs and slippage are large relative to the intraday edge.",
            "Wide opening ranges on gap days produce oversized stops or skipped trades.",
        ],
        best_for="Intraday trading of liquid NSE names with clean 1-5 minute data.",
        warning="Breakout strategies are sensitive to transaction costs and false breakouts.",
        required_data=["Intraday OHLCV bars covering the opening range through square-off",
                       "benchmark intraday bars if market_trend_filter is on"],
        example=(
            "5-minute bars, OR 09:15-09:30: if the 09:35 bar closes above the 09:15-09:30 high on "
            ">1.5x the average opening-range bar volume, a long is taken with a 0.5% stop and 1% "
            "target, force-flat by 15:15. Mechanics only, not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._state: dict[str, _DayState] = {}
        self._or_start = _parse_hhmm("09:15")
        self._or_end = _parse_hhmm("09:30")
        self._sq_off = _parse_hhmm("15:15")
        self._or_start = _parse_hhmm(self.p["opening_range_start"])
        self._or_end = _parse_hhmm(self.p["opening_range_end"])
        self._sq_off = _parse_hhmm(self.p["square_off_time"])
        self._weekdays = {int(x) for x in str(self.p["allowed_weekdays"]).split(",") if x.strip() != ""}

    def on_bar(self, bar: Bar) -> None:
        self.ingest(bar)
        sym = bar.instrument
        if self.p["market_trend_filter"] and sym == self.p["regime_benchmark"]:
            return  # benchmark is data-only

        dt = self.bar_dt(bar)
        st = self._state.get(sym)
        if st is None or st.day != dt.date():
            st = _DayState(day=dt.date())
            self._state[sym] = st

        t = dt.time()
        price = float(bar.close)

        # session VWAP accumulation (whole day)
        typ = (float(bar.high) + float(bar.low) + price) / 3.0
        st.session_pv += typ * float(bar.volume or 0.0)
        st.session_v += float(bar.volume or 0.0)

        # forced square-off
        if t >= self._sq_off:
            if st.open_side is not None:
                self._flat(sym, st, price)
            return

        if dt.weekday() not in self._weekdays:
            return

        # build / lock the opening range
        if t < self._or_end:
            if self._or_start <= t < self._or_end:
                st.or_high = max(st.or_high, float(bar.high)) if st.bar_count_in_or else float(bar.high)
                st.or_low = min(st.or_low, float(bar.low)) if st.bar_count_in_or else float(bar.low)
                st.or_volume += float(bar.volume or 0.0)
                st.or_volumes.append(float(bar.volume or 0.0))
                st.bar_count_in_or += 1
            return
        if not st.or_locked:
            st.or_locked = st.bar_count_in_or > 0

        if st.open_side is not None:
            if self._manage_open(sym, st, bar):
                return
            return
        if st.or_locked:
            self._maybe_enter(sym, st, bar)

    # --- entries / exits -------------------------------------------

    def _vwap(self, st: _DayState) -> float | None:
        return st.session_pv / st.session_v if st.session_v > 0 else None

    def _benchmark_trend(self) -> str | None:
        buf = self._buffers.get(self.p["regime_benchmark"])
        if buf is None or len(buf.closes) < int(self.p["regime_trend_lookback"]):
            return None
        avg = sma(list(buf.closes), int(self.p["regime_trend_lookback"]))
        if avg is None:
            return None
        return "up" if buf.closes[-1] >= avg else "down"

    def _daily_loss_hit(self, st: _DayState) -> bool:
        cap = float(self.p["capital_allocation"])
        limit = float(self.p["max_daily_loss_pct"])
        return bool(limit and st.realized_pnl <= -cap * limit / 100.0)

    def _maybe_enter(self, sym: str, st: _DayState, bar: Bar) -> None:
        if self._daily_loss_hit(st):
            return
        if (st.long_trades + st.short_trades) >= int(self.p["max_trades_per_day"]):
            return
        price = float(bar.close)
        vol = float(bar.volume or 0.0)
        mean_or_vol = (sum(st.or_volumes) / len(st.or_volumes)) if st.or_volumes else 0.0
        vol_ok = mean_or_vol <= 0 or vol >= float(self.p["volume_multiplier"]) * mean_or_vol
        vwap_val = self._vwap(st)
        trend = self._benchmark_trend() if self.p["market_trend_filter"] else None

        long_ok = (
            price > st.or_high
            and vol_ok
            and st.long_trades < int(self.p["max_long_trades_per_day"])
            and (not self.p["use_vwap_filter"] or (vwap_val is not None and price > vwap_val))
            and (trend != "down")
        )
        short_ok = (
            self.p["allow_short"]
            and price < st.or_low
            and vol_ok
            and st.short_trades < int(self.p["max_short_trades_per_day"])
            and (not self.p["use_vwap_filter"] or (vwap_val is not None and price < vwap_val))
            and (trend != "up")
        )
        if long_ok:
            self._enter(sym, st, "long", bar)
        elif short_ok:
            self._enter(sym, st, "short", bar)

    def _stop_distance(self, sym: str, price: float) -> float:
        if float(self.p["atr_stop_mult"]) > 0:
            buf = self._buffer(sym)
            a = atr(list(buf.highs), list(buf.lows), list(buf.closes), int(self.p["atr_period"]))
            if a:
                return float(self.p["atr_stop_mult"]) * a
        return price * float(self.p["stop_loss_pct"]) / 100.0

    def _enter(self, sym: str, st: _DayState, side: str, bar: Bar) -> None:
        price = float(bar.close)
        stop_dist = self._stop_distance(sym, price)
        qty = self.size_position(price, stop_distance=stop_dist, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        st.open_side = side
        st.entry_price = price
        st.extreme = price
        if side == "long":
            st.stop_price = price - stop_dist
            st.target_price = price * (1 + float(self.p["target_pct"]) / 100.0) if self.p["target_pct"] else 0.0
            st.long_trades += 1
        else:
            st.stop_price = price + stop_dist
            st.target_price = price * (1 - float(self.p["target_pct"]) / 100.0) if self.p["target_pct"] else 0.0
            st.short_trades += 1

    def _manage_open(self, sym: str, st: _DayState, bar: Bar) -> bool:
        price = float(bar.close)
        trail = float(self.p["trailing_stop_pct"]) / 100.0
        if st.open_side == "long":
            st.extreme = max(st.extreme, price)
            if trail:
                st.stop_price = max(st.stop_price, st.extreme * (1 - trail))
            if price <= st.stop_price or (st.target_price and price >= st.target_price):
                self._flat(sym, st, price)
                return True
        else:
            st.extreme = min(st.extreme, price)
            if trail:
                st.stop_price = min(st.stop_price, st.extreme * (1 + trail))
            if price >= st.stop_price or (st.target_price and price <= st.target_price):
                self._flat(sym, st, price)
                return True
        return False

    def _flat(self, sym: str, st: _DayState, price: float) -> None:
        if st.open_side is None:
            return
        held = self.position(sym)
        if held != 0:
            self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
        direction = 1.0 if st.open_side == "long" else -1.0
        st.realized_pnl += direction * (price - st.entry_price) * abs(held or 0)
        st.open_side = None
        st.stop_price = st.target_price = 0.0

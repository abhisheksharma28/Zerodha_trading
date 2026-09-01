"""
Opening Breakout — NSE
Research-faithful implementation of:

"A Profitable Day Trading Strategy for the U.S. Equity Market"
Zarattini, Barbon & Aziz

PRIMARY CONFIGURATION
---------------------
5-minute Opening Range Breakout
RVOL >= 1.0
Top 20 Stocks in Play
Previous 14 sessions
10% of 14-day ATR stop
1% risk per trade
Intraday only
NSE session: 09:15–15:30 IST

IMPORTANT
---------
The research paper was developed for the U.S. equity market.

This implementation ports the METHODOLOGY to NSE.
The original US price / volume / ATR filters are NOT blindly
converted to India.

The NSE filter parameters are configurable and should be
calibrated using NSE historical data.

The research paper uses an actual stop order at the opening
range high/low. If the underlying backtest engine does not
support native stop orders, this implementation uses the
least optimistic available alternative: confirmation at/above
the breakout level using the available bar price.

NO LOOK-AHEAD
-------------
All selection information comes only from:
- completed opening range
- previous closed sessions
- previous 14 opening intervals
- previous 14 daily sessions

Today's later price action is never used for stock selection.

PRIMARY PRODUCTION STRATEGY
---------------------------
Top 20.

Top 5 / 10 / 20 / 30 should be tested separately as robustness
experiments. They do NOT replace the primary Top 20 configuration.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import date, time, timedelta, timezone
from typing import Any, ClassVar

from app.backtesting.timeframes import INTRADAY_TIMEFRAMES
from app.strategies.base import Bar
from app.strategies.indicators import atr as wilder_atr
from app.strategies.library.base import (
    ParamSpec,
    TemplateMetadata,
    TemplateStrategy,
    preset,
)

# ============================================================
# CONSTANTS
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)

DEFAULT_OPENING_RANGE_MINUTES = 5
DEFAULT_RVOL_LOOKBACK = 14
DEFAULT_ATR_PERIOD = 14

# Research paper values
DEFAULT_RVOL_MIN = 1.0
DEFAULT_TOP_N = 20
DEFAULT_ATR_STOP_FRACTION = 0.10
DEFAULT_RISK_PER_TRADE = 1.0


# ============================================================
# HELPERS
# ============================================================

def _parse_hhmm(value: str) -> time:
    """Parse HH:MM."""
    hh, mm = value.strip().split(":")
    return time(int(hh), int(mm))


def _time_plus(t: time, minutes: int) -> time:
    """Add minutes to a time."""
    base = timedelta(hours=t.hour, minutes=t.minute)
    base += timedelta(minutes=minutes)

    total_minutes = int(base.total_seconds() // 60)

    return time(
        (total_minutes // 60) % 24,
        total_minutes % 60,
    )


# ============================================================
# DAILY STATE
# ============================================================

@dataclass
class _Day:
    day: date

    # Opening range
    or_open: float = 0.0
    or_high: float = 0.0
    or_low: float = 0.0
    or_close: float = 0.0
    or_volume: float = 0.0
    or_bars: int = 0
    or_locked: bool = False

    # Daily running values
    day_high: float = 0.0
    day_low: float = 0.0
    day_close: float = 0.0
    day_volume: float = 0.0

    # Selection
    rvol: float = 0.0
    atr_value: float = 0.0
    mean_or_volume: float = 0.0
    mean_daily_volume: float = 0.0

    eligible: bool = False
    armed: bool = False

    # Trade state
    done: bool = False
    side: str | None = None

    entry_ref: float = 0.0
    stop_price: float = 0.0
    stop_distance: float = 0.0
    quantity: int = 0

    # Diagnostics
    rejection_reason: str | None = None


@dataclass
class _Hist:
    """
    Historical information for ONE instrument.

    All values represent CLOSED previous sessions.
    """

    # Previous opening interval volumes
    or_volumes: deque[float]

    # Previous daily H/L/C
    day_hlc: deque[tuple[float, float, float]]

    # Previous daily volume
    day_volumes: deque[float]


# ============================================================
# STRATEGY
# ============================================================

class OpeningBreakoutUSStrategy(TemplateStrategy):

    SLUG: ClassVar[str] = "opening-breakout-us"
    NAME: ClassVar[str] = "opening breakout NSE"
    CATEGORY: ClassVar[str] = "Breakout"

    MIN_INSTRUMENTS: ClassVar[int] = 2
    # Intraday-only: the strategy is built around the 09:15 opening interval
    # and squares off same day. Daily bars would make it inert.
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = INTRADAY_TIMEFRAMES

    # ========================================================
    # PARAMETERS
    # ========================================================

    PARAMS: ClassVar[dict[str, ParamSpec]] = {

        # ----------------------------------------------------
        # Opening range
        # ----------------------------------------------------

        "opening_range_minutes": ParamSpec(
            "enum",
            "5",
            (
                "Opening range length in minutes from 09:15 IST. "
                "5 minutes is the PRIMARY research configuration. "
                "15/30/60 may be used only for robustness testing."
            ),
            choices=("5", "15", "30", "60"),
        ),

        # ----------------------------------------------------
        # RVOL
        # ----------------------------------------------------

        "rvol_min": ParamSpec(
            "number",
            1.0,
            (
                "Minimum opening-interval relative volume. "
                "1.0 means today's opening interval volume must be "
                "at least the average of the previous 14 sessions."
            ),
            min=0.0,
            max=100.0,
        ),

        "top_n": ParamSpec(
            "integer",
            20,
            (
                "Number of highest-RVOL eligible stocks traded each day. "
                "PRIMARY research configuration = 20. "
                "Robustness experiments = 5 / 10 / 20 / 30."
            ),
            min=1,
            max=500,
        ),

        "rvol_lookback": ParamSpec(
            "integer",
            14,
            (
                "Previous trading sessions used to calculate opening "
                "interval RVOL."
            ),
            min=2,
            max=120,
        ),

        # ----------------------------------------------------
        # Session
        # ----------------------------------------------------

        "square_off_time": ParamSpec(
            "string",
            "15:25",
            (
                "Force-flat time in IST. Must be a bar-start time the data "
                "actually reaches: on 5-minute NSE data the last regular "
                "session candle starts at 15:25, so 15:30 would never trigger "
                "and positions would leak overnight. 15:25 keeps everything "
                "flat before the 15:30 close."
            ),
        ),

        "allowed_weekdays": ParamSpec(
            "string",
            "0,1,2,3,4",
            "Weekdays allowed. Monday=0, Friday=4.",
        ),

        "allow_short": ParamSpec(
            "boolean",
            True,
            (
                "Allow bearish opening-range short trades. "
                "Requires the instrument and broker to support "
                "intraday short selling."
            ),
        ),

        # ----------------------------------------------------
        # NSE liquidity filters
        #
        # IMPORTANT:
        # These are configurable placeholders.
        # They are NOT claimed to be paper-equivalent.
        # ----------------------------------------------------

        "min_open_price": ParamSpec(
            "number",
            50.0,
            (
                "Minimum opening price in INR. "
                "NSE calibration parameter. "
                "Do not interpret as a direct conversion of the "
                "paper's $5 filter."
            ),
            min=0.0,
            group="filter",
        ),

        "min_avg_daily_volume": ParamSpec(
            "number",
            500_000.0,
            (
                "Minimum average daily volume over previous 14 sessions. "
                "NSE calibration parameter."
            ),
            min=0.0,
            group="filter",
        ),

        "min_atr": ParamSpec(
            "number",
            1.0,
            (
                "Minimum 14-day daily ATR in INR. "
                "NSE calibration parameter."
            ),
            min=0.0,
            group="filter",
        ),

        # ----------------------------------------------------
        # Risk
        # ----------------------------------------------------

        "atr_period": ParamSpec(
            "integer",
            14,
            "Daily ATR lookback.",
            min=2,
            max=100,
            group="risk",
        ),

        "atr_stop_fraction": ParamSpec(
            "number",
            0.10,
            (
                "Initial stop distance = 10% of daily ATR. "
                "This is directly based on the research paper."
            ),
            min=0.001,
            max=5.0,
            group="risk",
        ),

        # ----------------------------------------------------
        # Execution
        # ----------------------------------------------------

        "exchange": ParamSpec(
            "string",
            "NSE",
            "Exchange used for orders.",
        ),

        "product": ParamSpec(
            "enum",
            "MIS",
            "Intraday product.",
            choices=("MIS", "NRML"),
        ),
    }

    # ========================================================
    # PRESETS
    # ========================================================

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {

        # Conservative is an experiment, NOT the research baseline.
        "conservative": preset(
            opening_range_minutes="5",
            rvol_min=2.0,
            top_n=10,
            allow_short=False,
            min_open_price=100.0,
            min_avg_daily_volume=1_000_000.0,
            min_atr=2.0,
            sizing_method="risk_per_trade",
            risk_per_trade_pct=0.5,
            max_position_size_pct=10.0,
            product="MIS",
        ),

        # PRIMARY
        "balanced": preset(
            opening_range_minutes="5",
            rvol_min=1.0,
            top_n=20,
            allow_short=True,

            # NSE calibration placeholders.
            min_open_price=50.0,
            min_avg_daily_volume=500_000.0,
            min_atr=1.0,

            sizing_method="risk_per_trade",
            risk_per_trade_pct=1.0,
            max_position_size_pct=20.0,
            product="MIS",
        ),

        # Experiment only.
        "aggressive": preset(
            opening_range_minutes="5",
            rvol_min=1.0,
            top_n=20,
            allow_short=True,

            min_open_price=30.0,
            min_avg_daily_volume=250_000.0,
            min_atr=0.5,

            sizing_method="risk_per_trade",
            risk_per_trade_pct=1.0,
            max_position_size_pct=25.0,
            product="MIS",
        ),
    }

    # ========================================================
    # METADATA
    # ========================================================

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(

        slug=SLUG,
        name=NAME,
        category=CATEGORY,

        description=(
            "Research-faithful 5-minute Opening Range Breakout "
            "filtered to the day's Stocks in Play using opening-"
            "interval Relative Volume. Primary NSE configuration "
            "trades the Top 20 highest-RVOL eligible names."
        ),

        logic=(
            "Each day: construct the 09:15-09:20 opening range. "
            "Calculate RVOL using today's opening-interval volume "
            "divided by the mean of the previous 14 opening intervals. "
            "Apply liquidity and ATR filters. Keep RVOL >= 1.0. "
            "Rank descending and select Top 20. "
            "Bullish opening range permits long only. "
            "Bearish opening range permits short only. "
            "Doji produces no trade. "
            "Stop distance = 10% of 14-day daily ATR. "
            "Risk = 1% of allocated capital. "
            "All positions are closed by 15:30."
        ),

        timeframe="5-minute intraday",

        market_types=[
            "NSE equities",
            "Indian cash market",
        ],

        supports_long=True,
        supports_short=True,
        supports_intraday=True,
        supports_swing=False,
        supports_market_neutral=False,

        complexity="High",
        time_horizon="Intraday",

        risks=[
            "US research results are not assumed to transfer to NSE.",
            "NSE price/volume/ATR filters require calibration.",
            "Transaction costs and slippage can materially affect ORB results.",
            "Opening breakout execution is sensitive to intrabar data quality.",
            "Top-N concentration can increase daily tail risk.",
            "Short selling must be operationally supported.",
            "Survivorship bias must be avoided in historical studies.",
        ],

        best_for=(
            "Testing whether the Stocks-in-Play opening-range breakout "
            "effect exists in the NSE equity market."
        ),

        warning=(
            "Research implementation only. Do not assume profitability. "
            "Validate using realistic NSE costs, slippage, walk-forward "
            "and out-of-sample testing before live trading."
        ),

        required_data=[
            "Complete 1-minute or 5-minute NSE OHLCV data.",
            "09:15 onward regular-session data.",
            "Previous 14 opening intervals for RVOL.",
            "Previous 14+ daily sessions for ATR.",
            "Point-in-time / survivorship-bias-free universe.",
            "Corporate-action-aware historical data.",
        ],

        example=(
            "On a 5-minute NSE session, calculate the 09:15-09:20 "
            "opening range and opening volume. Compare that volume "
            "against the stock's previous 14 opening intervals. "
            "Rank qualifying stocks by RVOL and trade the Top 20."
        ),
    )

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(self, context) -> None:

        super().__init__(context)

        # Current day state by symbol
        self._day: dict[str, _Day] = {}

        # Historical state by symbol
        self._hist: dict[str, _Hist] = {}

        # Current session
        self._current_day: date | None = None

        # Whether today's cross-sectional ranking is finalized
        self._ranking_finalized: bool = False

        # Opening range
        self._or_minutes = int(
            self.p["opening_range_minutes"]
        )

        self._or_end = _time_plus(
            SESSION_OPEN,
            self._or_minutes,
        )

        # Square-off
        self._sq_off = _parse_hhmm(
            self.p["square_off_time"]
        )

        # Weekdays
        self._weekdays = {
            int(x.strip())
            for x in str(
                self.p["allowed_weekdays"]
            ).split(",")
            if x.strip()
        }

        # Lookbacks
        self._atr_period = int(
            self.p["atr_period"]
        )

        self._rvol_lookback = int(
            self.p["rvol_lookback"]
        )

        # Diagnostics
        self._diagnostics: Counter[str] = Counter()

        self._last_ranked_date: date | None = None

    # ========================================================
    # HISTORY
    # ========================================================

    def _hist_for(self, sym: str) -> _Hist:

        hist = self._hist.get(sym)

        if hist is None:

            hist = _Hist(
                or_volumes=deque(
                    maxlen=self._rvol_lookback
                ),

                day_hlc=deque(
                    maxlen=max(
                        self._atr_period + 5,
                        self._atr_period + 1,
                    )
                ),

                day_volumes=deque(
                    maxlen=self._rvol_lookback
                ),
            )

            self._hist[sym] = hist

        return hist

    def _finalize_day(
        self,
        sym: str,
        st: _Day,
    ) -> None:
        """
        Move completed session information into history.

        IMPORTANT:
        Only closed sessions are added.

        This prevents today's opening volume and today's daily
        range from contaminating tomorrow's calculations.
        """

        hist = self._hist_for(sym)

        # Opening interval volume
        if st.or_bars > 0:
            hist.or_volumes.append(
                float(st.or_volume)
            )

        # Daily HLC
        if (
            st.day_close > 0
            and st.day_high > 0
            and st.day_low > 0
        ):
            hist.day_hlc.append(
                (
                    float(st.day_high),
                    float(st.day_low),
                    float(st.day_close),
                )
            )

            hist.day_volumes.append(
                float(st.day_volume)
            )

    def _daily_atr(
        self,
        sym: str,
    ) -> float | None:
        """
        Calculate ATR using CLOSED previous sessions only.
        """

        hist = self._hist.get(sym)

        if hist is None:
            return None

        # Wilder ATR generally requires period + 1 closes/ranges.
        if len(hist.day_hlc) < self._atr_period + 1:
            return None

        highs = [
            x[0]
            for x in hist.day_hlc
        ]

        lows = [
            x[1]
            for x in hist.day_hlc
        ]

        closes = [
            x[2]
            for x in hist.day_hlc
        ]

        value = wilder_atr(
            highs,
            lows,
            closes,
            self._atr_period,
        )

        if value is None:
            return None

        return float(value)

    # ========================================================
    # SESSION RESET
    # ========================================================

    def _start_new_day(
        self,
        d: date,
    ) -> None:
        """
        Finalize previous-day states and reset cross-sectional
        ranking state.

        This is intentionally independent of which symbol receives
        the first bar of the new day.
        """

        if (
            self._current_day is not None
            and self._current_day != d
        ):
            for sym, st in list(
                self._day.items()
            ):
                if st.day == self._current_day:
                    # Safety net: if intraday square-off never fired (e.g. a
                    # coarser timeframe whose last bar is before square_off_time,
                    # or missing tail candles), never carry a position overnight.
                    if st.side is not None or self.position(sym) != 0:
                        self._flatten(sym, st)
                    self._finalize_day(sym, st)

        self._current_day = d
        self._ranking_finalized = False
        self._last_ranked_date = None

        self._diagnostics.clear()

    # ========================================================
    # OPENING RANGE
    # ========================================================

    def _update_opening_range(
        self,
        st: _Day,
        bar: Bar,
    ) -> None:

        o = float(bar.open)
        h = float(bar.high)
        lo = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume or 0.0)

        if st.or_bars == 0:

            st.or_open = o
            st.or_high = h
            st.or_low = lo

        else:

            st.or_high = max(
                st.or_high,
                h,
            )

            st.or_low = min(
                st.or_low,
                lo,
            )

        st.or_close = c
        st.or_volume += v
        st.or_bars += 1

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    def _diagnostic_reject(
        self,
        reason: str,
    ) -> None:

        self._diagnostics[
            reason
        ] += 1
        # mirror into the engine's run diagnostics (opt-in hook, no effect
        # on strategy logic) so a zero-trade run can name the failing stage
        self.context.note_signal(f"reject:{reason}")

    def _print_diagnostics(
        self,
        d: date,
        scored: list[tuple[float, str]],
    ) -> None:

        print(
            "\n"
            + "=" * 80
        )

        print(
            f"OPENING BREAKOUT DIAGNOSTICS | {d}"
        )

        print(
            f"Opening range: "
            f"09:15 -> {self._or_end.strftime('%H:%M')}"
        )

        print(
            f"RVOL minimum: "
            f"{float(self.p['rvol_min']):.2f}"
        )

        print(
            f"Requested Top N: "
            f"{int(self.p['top_n'])}"
        )

        print(
            f"Symbols received: "
            f"{len(self._day)}"
        )

        complete_or = sum(
            1
            for st in self._day.values()
            if (
                st.day == d
                and st.or_bars > 0
                and st.or_locked
            )
        )

        print(
            f"Complete opening ranges: "
            f"{complete_or}"
        )

        print(
            f"RVOL-qualified stocks: "
            f"{len(scored)}"
        )

        print(
            "Rejection counts:"
        )

        if self._diagnostics:
            for reason, count in sorted(
                self._diagnostics.items()
            ):
                print(
                    f"  {reason}: {count}"
                )
        else:
            print(
                "  none"
            )

        top_n = int(
            self.p["top_n"]
        )

        print(
            f"\nTOP {top_n} STOCKS IN PLAY:"
        )

        if not scored:

            print(
                "  NONE"
            )

        else:

            for rank, (
                rvol,
                sym,
            ) in enumerate(
                scored[:top_n],
                start=1,
            ):

                st = self._day[sym]

                direction = (
                    "LONG"
                    if st.or_close > st.or_open
                    else "SHORT"
                    if st.or_close < st.or_open
                    else "DOJI"
                )

                print(
                    f"  {rank:02d}. "
                    f"{sym:<20} "
                    f"RVOL={rvol:.2f} "
                    f"OR={st.or_open:.2f}/"
                    f"{st.or_high:.2f}/"
                    f"{st.or_low:.2f}/"
                    f"{st.or_close:.2f} "
                    f"DIR={direction}"
                )

        print(
            "=" * 80
            + "\n"
        )

    # ========================================================
    # RANKING
    # ========================================================

    def _rank_and_arm(
        self,
        d: date,
    ) -> None:
        """
        Cross-sectional Stocks-in-Play selection.

        IMPORTANT:
        Ranking is performed exactly once per trading day.

        The old implementation used:

            if _ranked_day != d:
                rank()

        directly from the first post-opening-range symbol.

        That is dangerous because the first symbol processed by
        the event loop does not necessarily represent the entire
        universe.

        Here we first lock all currently known opening ranges and
        then rank only completed opening ranges.
        """

        if self._ranking_finalized:
            return

        # ----------------------------------------------------
        # First lock all completed opening ranges.
        # ----------------------------------------------------

        for st in self._day.values():

            if st.day != d:
                continue

            if st.or_bars <= 0:
                continue

            st.or_locked = True

        # ----------------------------------------------------
        # Build candidate list.
        # ----------------------------------------------------

        scored: list[
            tuple[float, str]
        ] = []

        for sym, st in self._day.items():

            if st.day != d:
                continue

            if st.or_bars <= 0:
                self._diagnostic_reject(
                    "missing_opening_range"
                )
                continue

            # ------------------------------------------------
            # Price filter
            # ------------------------------------------------

            if (
                st.or_open
                < float(
                    self.p["min_open_price"]
                )
            ):

                st.rejection_reason = (
                    "price_filter"
                )

                self._diagnostic_reject(
                    "price_filter"
                )

                continue

            # ------------------------------------------------
            # Historical data
            # ------------------------------------------------

            hist = self._hist.get(sym)

            if hist is None:

                st.rejection_reason = (
                    "missing_history"
                )

                self._diagnostic_reject(
                    "missing_history"
                )

                continue

            # ------------------------------------------------
            # RVOL history
            # ------------------------------------------------

            if (
                len(hist.or_volumes)
                < self._rvol_lookback
            ):

                st.rejection_reason = (
                    "insufficient_rvol_history"
                )

                self._diagnostic_reject(
                    "insufficient_rvol_history"
                )

                continue

            # ------------------------------------------------
            # Daily volume history
            # ------------------------------------------------

            if (
                len(hist.day_volumes)
                < self._rvol_lookback
            ):

                st.rejection_reason = (
                    "insufficient_daily_volume_history"
                )

                self._diagnostic_reject(
                    "insufficient_daily_volume_history"
                )

                continue

            # ------------------------------------------------
            # Mean opening volume
            # ------------------------------------------------

            mean_or_volume = (
                sum(hist.or_volumes)
                / len(hist.or_volumes)
            )

            st.mean_or_volume = (
                mean_or_volume
            )

            if mean_or_volume <= 0:

                st.rejection_reason = (
                    "zero_mean_opening_volume"
                )

                self._diagnostic_reject(
                    "zero_mean_opening_volume"
                )

                continue

            # ------------------------------------------------
            # Mean daily volume
            # ------------------------------------------------

            mean_daily_volume = (
                sum(hist.day_volumes)
                / len(hist.day_volumes)
            )

            st.mean_daily_volume = (
                mean_daily_volume
            )

            if (
                mean_daily_volume
                < float(
                    self.p["min_avg_daily_volume"]
                )
            ):

                st.rejection_reason = (
                    "average_volume_filter"
                )

                self._diagnostic_reject(
                    "average_volume_filter"
                )

                continue

            # ------------------------------------------------
            # ATR
            # ------------------------------------------------

            atr_value = self._daily_atr(sym)

            if atr_value is None:

                st.rejection_reason = (
                    "insufficient_atr_history"
                )

                self._diagnostic_reject(
                    "insufficient_atr_history"
                )

                continue

            st.atr_value = atr_value

            if (
                atr_value
                < float(
                    self.p["min_atr"]
                )
            ):

                st.rejection_reason = (
                    "atr_filter"
                )

                self._diagnostic_reject(
                    "atr_filter"
                )

                continue

            # ------------------------------------------------
            # RVOL
            #
            # EXACT methodology:
            #
            # today's opening interval volume /
            # average opening interval volume
            # over previous 14 sessions
            # ------------------------------------------------

            rvol = (
                st.or_volume
                / mean_or_volume
            )

            st.rvol = rvol

            if (
                rvol
                < float(
                    self.p["rvol_min"]
                )
            ):

                st.rejection_reason = (
                    "rvol_filter"
                )

                self._diagnostic_reject(
                    "rvol_filter"
                )

                continue

            # ------------------------------------------------
            # Candidate
            # ------------------------------------------------

            st.eligible = True

            scored.append(
                (
                    rvol,
                    sym,
                )
            )

        # ----------------------------------------------------
        # Deterministic ranking
        # ----------------------------------------------------

        scored.sort(
            key=lambda x: (
                -x[0],
                x[1],
            )
        )

        # ----------------------------------------------------
        # Arm Top N only
        # ----------------------------------------------------

        top_n = int(
            self.p["top_n"]
        )

        selected = scored[:top_n]
        self.context.note_signal("rvol_qualified", len(scored))
        self.context.note_signal("armed", len(selected))

        for _, sym in selected:

            self._day[
                sym
            ].armed = True

        # ----------------------------------------------------
        # Diagnostics
        # ----------------------------------------------------

        self._print_diagnostics(
            d,
            scored,
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # Mark ranking final only AFTER the complete selection
        # has been constructed.
        # ----------------------------------------------------

        self._ranking_finalized = True
        self._last_ranked_date = d

    # ========================================================
    # ENTRY
    # ========================================================

    def _maybe_enter(
        self,
        sym: str,
        st: _Day,
        bar: Bar,
    ) -> None:

        # ----------------------------------------------------
        # Determine direction from opening range.
        # ----------------------------------------------------

        if (
            st.or_close
            > st.or_open
        ):

            side = "long"

        elif (
            st.or_close
            < st.or_open
        ):

            side = "short"

        else:

            # Doji = no trade.
            st.rejection_reason = (
                "opening_range_doji"
            )

            self._diagnostic_reject(
                "opening_range_doji"
            )

            return

        # ----------------------------------------------------
        # Short permission
        # ----------------------------------------------------

        if (
            side == "short"
            and not bool(
                self.p["allow_short"]
            )
        ):

            st.rejection_reason = (
                "short_disabled"
            )

            self._diagnostic_reject(
                "short_disabled"
            )

            return

        # ----------------------------------------------------
        # Never enter at or after square-off.
        # ----------------------------------------------------

        dt = self.bar_dt(bar)

        if dt.time() >= self._sq_off:
            return

        # ----------------------------------------------------
        # Breakout trigger.
        #
        # Research paper:
        #
        # LONG:
        # stop-buy at opening-range HIGH
        #
        # SHORT:
        # stop-sell at opening-range LOW
        #
        # If the execution engine has native stop-order support,
        # this section should be wired to that API.
        #
        # For a close-based backtest engine, we use the current
        # bar close as the non-optimistic executable price once
        # the breakout level has been crossed.
        # ----------------------------------------------------

        close = float(
            bar.close
        )

        if (
            side == "long"
            and close < st.or_high
        ):
            return

        if (
            side == "short"
            and close > st.or_low
        ):
            return

        # ----------------------------------------------------
        # ATR
        # ----------------------------------------------------

        atr_value = self._daily_atr(
            sym
        )

        if (
            atr_value is None
            or atr_value <= 0
        ):
            return

        # ----------------------------------------------------
        # Stop distance
        #
        # 10% of ATR
        # ----------------------------------------------------

        stop_distance = (
            float(
                self.p["atr_stop_fraction"]
            )
            * atr_value
        )

        if stop_distance <= 0:
            return

        # ----------------------------------------------------
        # Position sizing
        #
        # Delegate to framework sizing engine so existing
        # capital allocation / risk controls remain respected.
        # ----------------------------------------------------

        qty = self.size_position(
            close,
            stop_distance=stop_distance,
            symbol=sym,
        )

        try:
            qty = int(qty)
        except (
            TypeError,
            ValueError,
        ):
            qty = 0

        if qty <= 0:
            return

        # ----------------------------------------------------
        # Submit
        # ----------------------------------------------------

        order_side = (
            "BUY"
            if side == "long"
            else "SELL"
        )

        print(
            "\n"
            + "-" * 80
        )

        print(
            "OPENING BREAKOUT ENTRY"
        )

        print(
            f"Date:        {dt.date()}"
        )

        print(
            f"Symbol:      {sym}"
        )

        print(
            f"Direction:   {side.upper()}"
        )

        print(
            f"RVOL:        {st.rvol:.2f}"
        )

        print(
            f"OR Open:     {st.or_open:.2f}"
        )

        print(
            f"OR High:     {st.or_high:.2f}"
        )

        print(
            f"OR Low:      {st.or_low:.2f}"
        )

        print(
            f"OR Close:    {st.or_close:.2f}"
        )

        print(
            f"ATR:         {atr_value:.4f}"
        )

        print(
            f"Entry:       {close:.2f}"
        )

        print(
            f"Stop:        "
            f"{(
                close - stop_distance
                if side == 'long'
                else close + stop_distance
            ): .2f}"
        )

        print(
            f"Qty:         {qty}"
        )

        print(
            "-" * 80
        )

        self.submit(
            sym,
            order_side,
            qty,
            exchange=self.p["exchange"],
            product=self.p["product"],
        )
        self.context.note_signal("breakout_entry")

        # ----------------------------------------------------
        # Save trade state
        # ----------------------------------------------------

        st.side = side
        st.done = True

        st.entry_ref = close
        st.stop_distance = stop_distance
        st.stop_price = (
            close - stop_distance
            if side == "long"
            else close + stop_distance
        )

        st.quantity = qty

    # ========================================================
    # EXIT
    # ========================================================

    def _flatten(
        self,
        sym: str,
        st: _Day,
    ) -> None:

        if self.position(sym) != 0:

            self.rebalance_to(
                sym,
                0,
                exchange=self.p["exchange"],
                product=self.p["product"],
            )

        st.side = None
        st.done = True
        st.stop_price = 0.0

    # ========================================================
    # POSITION MANAGEMENT
    # ========================================================

    def _manage_position(
        self,
        sym: str,
        st: _Day,
        bar: Bar,
    ) -> bool:
        """
        Returns True if this bar was consumed by position
        management and should not be processed for a new entry.
        """

        held = self.position(sym)

        if (
            st.side is None
            or held == 0
        ):
            return False

        dt = self.bar_dt(bar)

        t = dt.time()

        # ----------------------------------------------------
        # Force square-off
        # ----------------------------------------------------

        if t >= self._sq_off:

            self._flatten(
                sym,
                st,
            )

            return True

        # ----------------------------------------------------
        # Stop loss
        # ----------------------------------------------------

        low = float(
            bar.low
        )

        high = float(
            bar.high
        )

        if (
            st.side == "long"
            and low <= st.stop_price
        ):

            self._flatten(
                sym,
                st,
            )

            return True

        if (
            st.side == "short"
            and high >= st.stop_price
        ):

            self._flatten(
                sym,
                st,
            )

            return True

        return True

    # ========================================================
    # MAIN BAR LOOP
    # ========================================================

    def on_bar(
        self,
        bar: Bar,
    ) -> None:

        # ----------------------------------------------------
        # Framework ingestion
        # ----------------------------------------------------

        self.ingest(bar)

        sym = bar.instrument

        dt = self.bar_dt(
            bar
        )

        d = dt.date()
        t = dt.time()

        # ----------------------------------------------------
        # New trading day
        # ----------------------------------------------------

        if (
            self._current_day != d
        ):

            self._start_new_day(
                d
            )

        # ----------------------------------------------------
        # Get/create today's state
        # ----------------------------------------------------

        st = self._day.get(sym)

        if (
            st is None
            or st.day != d
        ):

            # If there is an old state for this symbol,
            # finalize it before replacing it.
            if (
                st is not None
                and st.day != d
            ):

                self._finalize_day(
                    sym,
                    st,
                )

            st = _Day(
                day=d
            )

            self._day[sym] = st

        # ----------------------------------------------------
        # Ignore weekends / non-trading weekdays
        # ----------------------------------------------------

        if (
            dt.weekday()
            not in self._weekdays
        ):
            return

        # ----------------------------------------------------
        # Ignore outside regular session for strategy logic.
        #
        # Daily state is updated only during regular session
        # as this strategy is NSE cash-market intraday.
        # ----------------------------------------------------

        if t < SESSION_OPEN:
            return

        if t >= SESSION_CLOSE:

            if self.position(sym) != 0:
                self._flatten(
                    sym,
                    st,
                )

            st.done = True

            return

        # ----------------------------------------------------
        # Update daily OHLCV
        # ----------------------------------------------------

        high = float(
            bar.high
        )

        low = float(
            bar.low
        )

        close = float(
            bar.close
        )

        volume = float(
            bar.volume or 0.0
        )

        if st.day_close == 0.0:

            st.day_high = high
            st.day_low = low

        else:

            st.day_high = max(
                st.day_high,
                high,
            )

            st.day_low = min(
                st.day_low,
                low,
            )

        st.day_close = close
        st.day_volume += volume

        # ----------------------------------------------------
        # Opening range
        # ----------------------------------------------------

        if t < self._or_end:

            self._update_opening_range(
                st,
                bar,
            )

            return

        # ----------------------------------------------------
        # Lock opening range
        # ----------------------------------------------------

        if not st.or_locked:

            if st.or_bars <= 0:

                st.rejection_reason = (
                    "missing_opening_range"
                )

                return

            st.or_locked = True

        # ----------------------------------------------------
        # IMPORTANT RANKING FIX
        #
        # The old code ranked immediately on the first symbol
        # after 09:20.
        #
        # That can produce:
        #
        # symbol A arrives -> rank
        # symbol B arrives -> too late
        # symbol C arrives -> too late
        #
        # causing incomplete Top 20 selection.
        #
        # We use a timestamp boundary and require the opening
        # interval to have been completed before finalizing.
        #
        # This code deliberately finalizes only once.
        # ----------------------------------------------------

        if (
            not self._ranking_finalized
            and t >= self._or_end
        ):

            self._rank_and_arm(
                d
            )

        # ----------------------------------------------------
        # Position management
        # ----------------------------------------------------

        if self._manage_position(
            sym,
            st,
            bar,
        ):

            return

        # ----------------------------------------------------
        # No new entries after square-off
        # ----------------------------------------------------

        if t >= self._sq_off:

            st.done = True

            return

        # ----------------------------------------------------
        # Trade eligibility
        # ----------------------------------------------------

        if st.done:
            return

        if not st.armed:
            return

        if not st.or_locked:
            return

        if self.position(sym) != 0:
            return

        # ----------------------------------------------------
        # Entry
        # ----------------------------------------------------

        self._maybe_enter(
            sym,
            st,
            bar,
        )

    # ========================================================
    # OPTIONAL DEBUG / REPORTING HELPERS
    # ========================================================

    def debug_state(
        self,
    ) -> dict[str, Any]:
        """
        Returns a compact internal state snapshot.

        Useful for debugging the backtest UI/API.
        """

        current_day = self._current_day

        current_symbols = [
            sym
            for sym, st in self._day.items()
            if (
                current_day is not None
                and st.day == current_day
            )
        ]

        armed = [
            sym
            for sym in current_symbols
            if self._day[sym].armed
        ]

        traded = [
            sym
            for sym in current_symbols
            if self._day[sym].side is not None
            or self._day[sym].done
        ]

        return {
            "current_day": (
                str(current_day)
                if current_day
                else None
            ),

            "opening_range_end":
                self._or_end.strftime(
                    "%H:%M"
                ),

            "square_off":
                self._sq_off.strftime(
                    "%H:%M"
                ),

            "ranking_finalized":
                self._ranking_finalized,

            "symbols_seen":
                len(current_symbols),

            "armed_symbols":
                len(armed),

            "traded_or_completed":
                len(traded),

            "armed":
                sorted(armed),

            "diagnostics":
                dict(self._diagnostics),
        }
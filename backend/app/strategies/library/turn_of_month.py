"""Turn-of-the-Month — hold the index only around the month boundary.

A long-documented calendar anomaly (Ariel 1987; Lakonishok & Smidt 1988;
McConnell & Xu 2008): equity index returns have historically been
concentrated in the last day or two of the month and the first few days of
the next, with the rest of the month roughly flat. This template holds the
instrument long only inside that window and sits in cash otherwise.

Not guaranteed profitable. Calendar effects decay as they get crowded and
can vanish for years; transaction costs on 12 round trips a year eat a thin
edge. Validate out-of-sample.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class TurnOfMonthStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "turn-of-month"
    NAME: ClassVar[str] = "Turn-of-the-Month"
    CATEGORY: ClassVar[str] = "Seasonality"
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = 5
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 5

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "enter_dom": ParamSpec("integer", 26, "Go long from this day-of-month onward (captures the "
                               "last ~3 trading days).", min=18, max=31),
        "exit_dom": ParamSpec("integer", 4, "Stay long until this day-of-month in the new month, "
                              "then flat.", min=1, max=12),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(enter_dom=27, exit_dom=3, product="MIS",
                               sizing_method="fixed_capital", max_position_size_pct=60.0),
        "balanced": preset(enter_dom=26, exit_dom=4, product="MIS",
                           sizing_method="fixed_capital", max_position_size_pct=90.0),
        "aggressive": preset(enter_dom=24, exit_dom=5, product="MIS",
                             sizing_method="fixed_capital", max_position_size_pct=100.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Holds the instrument long only from enter_dom of each month through exit_dom "
                     "of the next; flat the rest of the time."),
        logic=("On each daily bar read the calendar day of month. If it is >= enter_dom, or it is "
               "<= exit_dom (i.e. early in a new month), target a full long position; otherwise "
               "target flat. One entry and one exit per month."),
        timeframe="day",
        market_types=["NSE broad indices / index ETFs (as a proxy)"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Low", time_horizon="Calendar",
        risks=["The effect is small, noisy and has weakened as it became well known.",
               "12 round trips a year — costs matter relative to the edge.",
               "A single bad month-end (event risk) can erase a year of the premium."],
        best_for="A tiny satellite overlay on a broad index, not a standalone book.",
        warning="A pure calendar bet with no price or trend confirmation.",
        required_data=["Daily bars for the index / ETF; only the bar dates are used for timing"],
        example=("On the NIFTY 50 index: go long at the close on the 26th of the month, exit at "
                 "the close on the 4th of the next. Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)

    def on_bar(self, bar: Bar) -> None:
        self.ingest(bar)
        sym = bar.instrument
        dom = self.bar_dt(bar).day
        in_window = dom >= int(self.p["enter_dom"]) or dom <= int(self.p["exit_dom"])

        if in_window and self.long_entries_allowed():
            price = float(bar.close)
            if price <= 0:
                return
            qty = self.size_position(price, symbol=sym)
            if qty > 0:
                self.rebalance_to(sym, qty, exchange=self.p["exchange"],
                                  product=self.p["product"])
        else:
            self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])

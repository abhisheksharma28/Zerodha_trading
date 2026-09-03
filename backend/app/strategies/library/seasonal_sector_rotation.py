"""Seasonal Sector Rotation — hold the sectors that this calendar month
has historically favoured.

Rotates on the *calendar*. From history seen so far it builds each NSE
sector index's **seasonal edge** per month — the month's return minus that
year's average month, so a sector that merely had a good year does not look
strong every month (Gultekin & Gultekin 1983; Keloharju et al. 2021). Each
month it holds the ``hold_n`` sectors whose edge for the month ahead is
strongest, positive often enough, and statistically distinguishable
(``min_t_stat``). A broad-index moving-average gate steps the book aside in
a falling market, where seasonality historically inverts (Kapalczynski
2022).

Not guaranteed profitable. Samples are small (one point per month per
year) and calendar edges decay once known. Validate out-of-sample; treat
it as a small overlay.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset
from app.strategies.seasonality import best_sectors_for_month, monthly_sector_stats


class SeasonalSectorRotationStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "seasonal-sector-rotation"
    NAME: ClassVar[str] = "Seasonal Sector Rotation"
    CATEGORY: ClassVar[str] = "Seasonality"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int | None] = 30
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 520

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "hold_n": ParamSpec("integer", 3, "How many top-ranked sectors to hold equal-weight.",
                            min=1, max=12),
        "min_years": ParamSpec("integer", 5, "A calendar month needs at least this many yearly "
                               "observations before the strategy will trade it.", min=2, max=15),
        "metric": ParamSpec("enum", "mean_pct", "Rank sectors by the seasonal-edge mean, median, "
                            "Kruskal-Wallis-style mean rank, or t-stat.",
                            choices=("mean_pct", "median_pct", "mean_rank", "t_stat")),
        "use_demeaned": ParamSpec("boolean", True, "Score the month's return relative to that "
                                  "year's average month (isolates the seasonal component)."),
        "min_hit_rate": ParamSpec("number", 0.5, "The month must have closed positive at least "
                                  "this often historically for the sector to be eligible.",
                                  min=0.0, max=1.0, group="filter"),
        "min_t_stat": ParamSpec("number", 0.8, "The month's seasonal edge must clear this "
                                "Student t-stat (0 disables the significance filter).",
                                min=0.0, max=4.0, group="filter"),
        "market_regime_ma": ParamSpec("integer", 200, "Only rotate while the broad index closes "
                              "above SMA(this); otherwise sit in cash (0 disables).",
                              min=0, max=400, group="filter"),
        "benchmark": ParamSpec("string", "NIFTY 50", "Broad index symbol for the regime gate "
                               "(must be one of the fed instruments)."),
        "history_window": ParamSpec("integer", 2600, "Bars of history used to build the seasonal "
                                    "table (~2600 = ten years).", min=300, max=4000),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "NRML", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(hold_n=2, min_years=6, metric="median_pct", use_demeaned=True,
                               min_hit_rate=0.6, min_t_stat=1.2, market_regime_ma=200,
                               history_window=2600, product="NRML",
                               sizing_method="fixed_capital", max_position_size_pct=45.0),
        "balanced": preset(hold_n=3, min_years=5, metric="mean_pct", use_demeaned=True,
                           min_hit_rate=0.5, min_t_stat=0.8, market_regime_ma=200,
                           history_window=2600, product="NRML",
                           sizing_method="fixed_capital", max_position_size_pct=35.0),
        "aggressive": preset(hold_n=4, min_years=4, metric="mean_rank", use_demeaned=True,
                             min_hit_rate=0.4, min_t_stat=0.0, market_regime_ma=0,
                             history_window=1800, product="NRML",
                             sizing_method="fixed_capital", max_position_size_pct=30.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Each month, hold the hold_n NSE sector indices whose historical record for "
                     "the coming calendar month is strongest, using only months that have already "
                     "finished."),
        logic=("On the first bar of a new month, for every sector index compute the return of "
               "each past (year, month) it has data for, group by calendar month, and take the "
               "mean/median and positive-hit-rate per month. Rank the sectors for the month ahead "
               "by the chosen metric, keep those with hit rate >= min_hit_rate and >= min_years "
               "observations, hold the top hold_n equal-weight, close the rest. The current, "
               "unfinished month is excluded from the table so the ranking is causal."),
        timeframe="day (monthly rotation)",
        market_types=["NSE sector indices (as sector-ETF / basket proxies)"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Positional / calendar",
        risks=["Small samples — one data point per month per year; patterns can be noise.",
               "Seasonal edges decay once widely known and traded.",
               "Sector indices are not directly tradable; real execution adds tracking error."],
        best_for="A small calendar-driven overlay on a sector sleeve.",
        warning="A backward-looking calendar bet with no price confirmation.",
        required_data=["Several years of daily closes for each sector index (more history = more "
                       "reliable month statistics)"],
        example=("11 NSE sector indices: entering November, the table says Auto and FMCG have the "
                 "best November record over the last 8 years with a >60% hit rate -> hold those "
                 "two for the month. Mechanics only, not advice."),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._last_month: tuple[int, int] | None = None

    def on_bar(self, bar: Bar) -> None:
        self.ingest(bar)
        dt = self.bar_dt(bar)
        ym = (dt.year, dt.month)
        if self._last_month is not None and ym != self._last_month:
            self._rebalance(dt.month, ym)
        self._last_month = ym

    def _flatten_all(self) -> None:
        for sym in self._buffers:
            self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])

    def _regime_ok(self) -> bool:
        ma = int(self.p["market_regime_ma"])
        if ma <= 0:
            return True
        buf = self._buffers.get(str(self.p["benchmark"]))
        if buf is None or len(buf.closes) < ma + 1:
            return True                       # no benchmark seen yet — don't block
        m = sma(list(buf.closes), ma)
        return m is not None and buf.closes[-1] > m

    def _rebalance(self, month: int, current_ym: tuple[int, int]) -> None:
        bench = str(self.p["benchmark"])
        if not self._regime_ok():
            self._flatten_all()
            return
        hw = int(self.p["history_window"])
        table_input: dict[str, list[Bar]] = {}
        for sym, buf in self._buffers.items():
            if sym == bench:
                continue
            bars = [b for b in list(buf.bars)[-hw:]
                    if (self.bar_dt(b).year, self.bar_dt(b).month) != current_ym]
            if bars:
                table_input[sym] = bars
        if len(table_input) < 2:
            return
        stats = monthly_sector_stats(table_input, min_years=int(self.p["min_years"]),
                                     demean=bool(self.p["use_demeaned"]))
        winners = best_sectors_for_month(
            stats, month, top_n=int(self.p["hold_n"]),
            metric=str(self.p["metric"]), min_hit_rate=float(self.p["min_hit_rate"]),
            min_t_stat=float(self.p["min_t_stat"]),
        )
        keep = {s for s, _v in winners}
        n = max(len(keep), 1)
        for sym, buf in self._buffers.items():
            price = buf.closes[-1] if buf.closes else 0.0
            if sym in keep and price > 0 and self.long_entries_allowed():
                slot = float(self.p["capital_allocation"]) / n
                qty = int(slot // price)
                self.rebalance_to(sym, max(qty, 0), exchange=self.p["exchange"],
                                  product=self.p["product"])
            else:
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])

"""Seasonal Sector *Stock* Rotation — hold real stocks from the sectors this
calendar month has historically favoured, filtered on technicals.

Same seasonal engine as ``seasonal-sector-rotation`` (build a month-by-month
sector-return table from history so far, pick the sectors whose record for
the month ahead is strongest), but instead of holding the sector index it
holds the individual stocks that (a) belong to those sectors — classified by
their rolling correlation to each sector index — and (b) pass a technical
gate (in an uptrend, positive trailing return, not overbought). A *current*
fundamentals quality gate is applied upstream, in the universe screen.

Not guaranteed profitable. Seasonal samples are small, correlation-based
sector labels are noisy, and the fundamentals gate is a mild look-ahead
(no point-in-time fundamentals exist). Validate out-of-sample.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.market_data.nse_universe import SECTOR_INDICES
from app.strategies.base import Bar
from app.strategies.indicators import roc, rsi, sma
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset
from app.strategies.seasonality import best_sectors_for_month, monthly_sector_stats

_SECTORS = set(SECTOR_INDICES)


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1.0
            for i in range(1, len(closes)) if closes[i - 1] > 0]


def _pearson(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 20:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return cov / (va * vb) ** 0.5 if va > 0 and vb > 0 else 0.0


class SeasonalSectorStockRotationStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "seasonal-sector-stock-rotation"
    NAME: ClassVar[str] = "Seasonal Sector Stock Rotation"
    CATEGORY: ClassVar[str] = "Seasonality"
    MIN_INSTRUMENTS: ClassVar[int] = 3
    MAX_INSTRUMENTS: ClassVar[int | None] = 220
    SUPPORTED_TIMEFRAMES: ClassVar[tuple[str, ...]] = ("1d",)
    MIN_BARS_REQUIRED: ClassVar[int] = 520

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "top_sectors": ParamSpec("integer", 2, "How many seasonally-strong sectors to draw "
                                 "stocks from each month.", min=1, max=6),
        "hold_n": ParamSpec("integer", 8, "Total stocks held equal-weight across those sectors.",
                            min=2, max=40),
        "corr_window": ParamSpec("integer", 252, "Window used to classify each stock to its "
                                 "most-correlated sector index.", min=60, max=750),
        "mom_lookback": ParamSpec("integer", 63, "Technical gate: the stock's trailing return "
                                  "over this window must be positive; also the ranking score.",
                                  min=10, max=400),
        "trend_ma_period": ParamSpec("integer", 100, "Technical gate: stock close must be above "
                              "SMA(this) (0 disables).", min=0, max=400, group="filter"),
        "rsi_period": ParamSpec("integer", 14, "Technical gate: RSI window.", min=2, max=50,
                                group="filter"),
        "rsi_max": ParamSpec("number", 75.0, "Technical gate: skip a stock with RSI above this "
                             "(overbought).", min=40.0, max=95.0, group="filter"),
        "min_years": ParamSpec("integer", 3, "A calendar month needs this many yearly "
                               "observations before its sectors are traded.", min=2, max=15),
        "min_hit_rate": ParamSpec("number", 0.5, "A sector's month must have closed positive at "
                                  "least this often historically.", min=0.0, max=1.0,
                                  group="filter"),
        "season_metric": ParamSpec("enum", "mean_pct", "Rank sectors by historical mean or "
                                   "median return for the month.", choices=("mean_pct", "median_pct")),
        "history_window": ParamSpec("integer", 2600, "Bars of sector-index history for the "
                                    "seasonal table (~2600 = ten years).", min=300, max=4000),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(top_sectors=2, hold_n=6, corr_window=252, mom_lookback=126,
                               trend_ma_period=200, rsi_max=70.0, min_years=5, min_hit_rate=0.6,
                               season_metric="median_pct", history_window=2600, product="CNC",
                               sizing_method="fixed_capital", max_position_size_pct=15.0),
        "balanced": preset(top_sectors=2, hold_n=8, corr_window=252, mom_lookback=63,
                           trend_ma_period=100, rsi_max=75.0, min_years=3, min_hit_rate=0.5,
                           season_metric="mean_pct", history_window=2600, product="CNC",
                           sizing_method="fixed_capital", max_position_size_pct=12.0),
        "aggressive": preset(top_sectors=3, hold_n=12, corr_window=189, mom_lookback=42,
                             trend_ma_period=0, rsi_max=82.0, min_years=3, min_hit_rate=0.4,
                             season_metric="mean_pct", history_window=1800, product="MIS",
                             sizing_method="fixed_capital", max_position_size_pct=10.0),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=("Each month, pick the sectors whose historical record for that calendar "
                     "month is strongest, then hold the individual stocks in those sectors that "
                     "are in an uptrend and not overbought."),
        logic=("On the first bar of a new month: (1) from sector-index history so far, build the "
               "return of each past (year, month), group by calendar month, and rank the sectors "
               "for the month ahead by mean/median return keeping hit rate >= min_hit_rate and "
               ">= min_years observations; take the top_sectors. (2) Classify every stock to the "
               "sector index it correlates with most over corr_window. (3) Keep stocks in the "
               "chosen sectors whose ROC(mom_lookback) > 0, close > SMA(trend_ma_period) and "
               "RSI(rsi_period) <= rsi_max. (4) Rank the survivors by ROC(mom_lookback), hold the "
               "top hold_n equal-weight, close the rest. A current-fundamentals quality gate is "
               "applied upstream in the universe screen."),
        timeframe="day (monthly rotation)",
        market_types=["NSE cash equities grouped by sector"],
        supports_long=True, supports_short=False, supports_intraday=False, supports_swing=True,
        supports_market_neutral=False,
        complexity="High", time_horizon="Positional / calendar",
        risks=["Seasonal samples are tiny (one point per month per year) and decay once known.",
               "Correlation-based sector labels drift and misclassify conglomerates.",
               "The fundamentals gate is not point-in-time — a mild look-ahead on stock quality.",
               "Concentrated: a few stocks in one or two sectors."],
        best_for="A calendar-driven satellite sleeve that expresses seasonality through real, "
                 "trending, fundamentally-sound stocks rather than an index.",
        warning="A backward-looking calendar bet; the technical gate is the only price confirmation.",
        required_data=["Several years of daily bars for each stock AND each NSE sector index"],
        example=("Entering July, the table says IT has the best July record over 8 years; hold "
                 "the 4 IT names that are above their 100-SMA with positive 3-month return and "
                 "RSI < 75. Mechanics only, not advice."),
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

    def _rebalance(self, month: int, current_ym: tuple[int, int]) -> None:
        hw = int(self.p["history_window"])
        sector_bars: dict[str, list[Bar]] = {}
        stock_syms: list[str] = []
        for sym, buf in self._buffers.items():
            if sym in _SECTORS:
                bs = [b for b in list(buf.bars)[-hw:]
                      if (self.bar_dt(b).year, self.bar_dt(b).month) != current_ym]
                if bs:
                    sector_bars[sym] = bs
            else:
                stock_syms.append(sym)
        if len(sector_bars) < 2 or not stock_syms:
            return

        stats = monthly_sector_stats(sector_bars, min_years=int(self.p["min_years"]))
        winners = best_sectors_for_month(
            stats, month, top_n=int(self.p["top_sectors"]),
            metric=str(self.p["season_metric"]), min_hit_rate=float(self.p["min_hit_rate"]))
        chosen = {s for s, _v in winners}
        if not chosen:
            self._flatten_all()
            return

        cw = int(self.p["corr_window"])
        ml = int(self.p["mom_lookback"])
        tm = int(self.p["trend_ma_period"])
        rp = int(self.p["rsi_period"])
        rmax = float(self.p["rsi_max"])
        # classify against ALL sectors, then require the stock's sector to be a chosen one
        sector_rets = {s: _returns([float(b.close) for b in bs][-cw:])
                       for s, bs in sector_bars.items()}

        ranked: list[tuple[str, float]] = []
        for sym in stock_syms:
            closes = list(self._buffers[sym].closes)
            if len(closes) < max(cw, ml, tm, rp) + 5:
                continue
            srets = _returns(closes[-cw:])
            best_sector = max(
                sector_rets, key=lambda sec: _pearson(srets, sector_rets[sec]), default=None)
            if best_sector is None or best_sector not in chosen:
                continue
            mom = roc(closes, ml)
            if mom is None or mom <= 0:
                continue
            if tm > 0:
                m = sma(closes, tm)
                if m is None or closes[-1] <= m:
                    continue
            r = rsi(closes, rp)
            if r is not None and r > rmax:
                continue
            ranked.append((sym, mom))

        ranked.sort(key=lambda kv: kv[1], reverse=True)
        keep = {s for s, _m in ranked[: int(self.p["hold_n"])]}
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

    def _flatten_all(self) -> None:
        for sym in self._buffers:
            self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])

"""Cross-Sectional Momentum — rank a universe, hold the strongest.

Each rebalance the strategy scores every eligible instrument by a weighted
blend of multi-horizon returns (optionally volatility-adjusted and/or
measured relative to a benchmark), ranks them, and targets an equal-weight
book of the top N (and, if enabled, a short book of the bottom N). Universe
eligibility is decided using only data available at the rebalance timestamp.

Not guaranteed profitable. Cross-sectional momentum suffers sharp drawdowns
in violent mean-reversion / "momentum crash" episodes. Validate with
out-of-sample and walk-forward tests and realistic turnover costs.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import rolling_volatility
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


class CrossSectionalMomentumStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "cross-sectional-momentum"
    NAME: ClassVar[str] = "Cross-Sectional Momentum"
    CATEGORY: ClassVar[str] = "Momentum"
    MIN_INSTRUMENTS: ClassVar[int] = 3

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "lookback_1": ParamSpec("integer", 20, "Short momentum lookback (bars).", min=2, max=500),
        "lookback_2": ParamSpec("integer", 60, "Medium momentum lookback (bars).", min=2, max=750),
        "lookback_3": ParamSpec("integer", 120, "Long momentum lookback (bars).", min=2, max=1000),
        "weight_1": ParamSpec("number", 0.30, "Weight on lookback_1 return.", min=0.0, max=1.0),
        "weight_2": ParamSpec("number", 0.40, "Weight on lookback_2 return.", min=0.0, max=1.0),
        "weight_3": ParamSpec("number", 0.30, "Weight on lookback_3 return.", min=0.0, max=1.0),
        "num_long_positions": ParamSpec("integer", 5, "Number of long positions.", min=0, max=200),
        "num_short_positions": ParamSpec("integer", 0, "Number of short positions.", min=0, max=200),
        "allow_short": ParamSpec("boolean", False, "Permit the short book."),
        "rebalance_frequency": ParamSpec("enum", "weekly", "How often to re-rank and rebalance.",
                                         choices=("daily", "weekly", "monthly")),
        "volatility_adjusted": ParamSpec("boolean", False,
                                         "Divide each horizon return by its realized volatility.",
                                         group="filter"),
        "use_relative_strength": ParamSpec("boolean", False,
                                           "Score relative to the benchmark's return.",
                                           group="filter"),
        "benchmark_symbol": ParamSpec("string", "NIFTY 50",
                                      "Benchmark tradingsymbol (must be in the stream).",
                                      group="filter"),
        "min_price": ParamSpec("number", 0.0, "Exclude instruments priced below this.",
                               min=0.0, group="filter"),
        "min_avg_volume": ParamSpec("number", 0.0,
                                    "Exclude instruments with 20-bar average volume below this.",
                                    min=0.0, group="filter"),
        "min_history_bars": ParamSpec("integer", 0,
                                      "Extra history required beyond the longest lookback.",
                                      min=0, max=2000, group="filter"),
        "max_volatility_pct": ParamSpec("number", 1000.0,
                                        "Exclude instruments whose per-bar realized vol (%) "
                                        "exceeds this.", min=0.0, max=5000.0, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            lookback_1=60, lookback_2=120, lookback_3=250, weight_1=0.2, weight_2=0.4, weight_3=0.4,
            num_long_positions=8, num_short_positions=0, allow_short=False,
            rebalance_frequency="monthly", volatility_adjusted=True, use_relative_strength=True,
            min_avg_volume=100000.0, max_position_size_pct=15.0,
        ),
        "balanced": preset(
            lookback_1=20, lookback_2=60, lookback_3=120, weight_1=0.3, weight_2=0.4, weight_3=0.3,
            num_long_positions=5, num_short_positions=0, allow_short=False,
            rebalance_frequency="weekly", volatility_adjusted=False,
            min_avg_volume=50000.0, max_position_size_pct=20.0,
        ),
        "aggressive": preset(
            lookback_1=10, lookback_2=30, lookback_3=60, weight_1=0.4, weight_2=0.4, weight_3=0.2,
            num_long_positions=5, num_short_positions=5, allow_short=True,
            rebalance_frequency="daily", volatility_adjusted=True, max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Ranks a stock universe by recent relative performance and holds an equal-weight book "
            "of the strongest names, rebalancing on a fixed cadence; can optionally short the "
            "weakest."
        ),
        logic=(
            "At each rebalance, for every instrument with enough clean history compute returns over "
            "lookback_1/2/3, optionally divide by realized volatility and/or subtract the "
            "benchmark's return, then blend with weight_1/2/3 into one score. Rank; target "
            "equal-weight longs in the top num_long_positions (and shorts in the bottom "
            "num_short_positions if allow_short). Positions not in the new target set are closed. "
            "Eligibility uses only data available at the rebalance bar."
        ),
        timeframe="day (weekly / monthly rebalance typical)",
        market_types=["NSE equity universes (NIFTY 50/100/200/500)"],
        supports_long=True, supports_short=True, supports_intraday=False, supports_swing=True,
        supports_market_neutral=True,
        complexity="High", time_horizon="Positional",
        risks=[
            "Momentum crashes: fast, deep drawdowns when leadership violently reverses.",
            "Turnover and transaction costs erode the raw signal, especially at daily cadence.",
            "Survivorship bias if the universe is today's constituents applied to the past.",
        ],
        best_for="Positional, diversified equity books rebalanced weekly or monthly.",
        warning="Momentum strategies can suffer during sharp reversals.",
        required_data=[
            "Daily OHLCV for every instrument in the universe",
            "at least lookback_3 + min_history_bars bars before the first rebalance",
            "benchmark bars in the stream if use_relative_strength is on",
        ],
        example=(
            "Universe of NIFTY 50 names, weekly rebalance, 5 longs: each Monday the 5 names with "
            "the highest blended 20/60/120-day return are held equal-weight for the week. "
            "Mechanics only, not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._last_seen_date: date | None = None
        self._last_rebalance_date: date | None = None

    def on_bar(self, bar: Bar) -> None:
        d = self.bar_dt(bar).date()
        # A date change means every instrument's buffer now holds complete
        # data through the prior period — rank BEFORE ingesting today's bar
        # so no future information can leak into the selection.
        if (
            self._last_seen_date is not None
            and d != self._last_seen_date
            and self._rebalance_due(d)
        ):
            self._rebalance(self._last_seen_date)
            self._last_rebalance_date = self._last_seen_date
        self._last_seen_date = d
        self.ingest(bar)

    # --- cadence -----------------------------------------------------

    def _rebalance_due(self, today: date) -> bool:
        if self._last_rebalance_date is None:
            return True
        freq = self.p["rebalance_frequency"]
        last = self._last_rebalance_date
        if freq == "daily":
            return today > last
        if freq == "weekly":
            return today.isocalendar()[:2] != last.isocalendar()[:2]
        return (today.year, today.month) != (last.year, last.month)

    # --- ranking + rebalance --------------------------------------

    def _eligible_score(self, sym: str) -> float | None:
        buf = self._buffers.get(sym)
        if buf is None:
            return None
        closes = list(buf.closes)
        vols = list(buf.volumes)
        longest = max(int(self.p["lookback_1"]), int(self.p["lookback_2"]),
                      int(self.p["lookback_3"]))
        if len(closes) < longest + 1 + int(self.p["min_history_bars"]):
            return None
        if closes[-1] < float(self.p["min_price"]):
            return None
        if float(self.p["min_avg_volume"]) > 0:
            recent_vol = vols[-20:] if len(vols) >= 20 else vols
            if recent_vol and (sum(recent_vol) / len(recent_vol)) < float(self.p["min_avg_volume"]):
                return None
        rv = rolling_volatility(closes, 20)
        if rv is not None and rv * 100.0 > float(self.p["max_volatility_pct"]):
            return None

        bench_closes = None
        if self.p["use_relative_strength"]:
            bbuf = self._buffers.get(self.p["benchmark_symbol"])
            bench_closes = list(bbuf.closes) if bbuf else None

        parts = []
        for lb, w in (
            (int(self.p["lookback_1"]), float(self.p["weight_1"])),
            (int(self.p["lookback_2"]), float(self.p["weight_2"])),
            (int(self.p["lookback_3"]), float(self.p["weight_3"])),
        ):
            if w == 0 or len(closes) < lb + 1 or closes[-1 - lb] == 0:
                continue
            r = closes[-1] / closes[-1 - lb] - 1.0
            if bench_closes is not None and len(bench_closes) >= lb + 1 and bench_closes[-1 - lb] != 0:
                r -= bench_closes[-1] / bench_closes[-1 - lb] - 1.0
            if self.p["volatility_adjusted"]:
                v = rolling_volatility(closes, lb)
                if v and v > 0:
                    r /= v
            parts.append(w * r)
        if not parts:
            return None
        return sum(parts)

    def _rebalance(self, as_of: date) -> None:
        bench = self.p["benchmark_symbol"] if self.p["use_relative_strength"] else None
        scores: dict[str, float] = {}
        for sym in self._buffers:
            if sym == bench:
                continue
            s = self._eligible_score(sym)
            if s is not None:
                scores[sym] = s
        if not scores:
            return

        ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
        n_long = min(int(self.p["num_long_positions"]), len(ranked))
        longs = ranked[:n_long]
        shorts: list[str] = []
        if self.p["allow_short"] and int(self.p["num_short_positions"]) > 0:
            n_short = min(int(self.p["num_short_positions"]), max(0, len(ranked) - n_long))
            shorts = ranked[len(ranked) - n_short:] if n_short else []

        capital = float(self.p["capital_allocation"])
        targets: dict[str, int] = {}
        if longs:
            per_name = capital / len(longs)
            for sym in longs:
                px = self._buffers[sym].closes[-1]
                qty = min(int(per_name // px), self._max_position_qty(px, capital)) if px > 0 else 0
                targets[sym] = qty
        if shorts:
            per_name = capital / len(shorts)
            for sym in shorts:
                px = self._buffers[sym].closes[-1]
                qty = min(int(per_name // px), self._max_position_qty(px, capital)) if px > 0 else 0
                targets[sym] = -qty

        # close anything held that isn't in the new target set
        for sym, held in list(self.context.positions.items()):
            if held != 0 and sym not in targets:
                targets[sym] = 0

        for sym, target_qty in targets.items():
            self.rebalance_to(sym, target_qty, exchange=self.p["exchange"],
                              product=self.p["product"])

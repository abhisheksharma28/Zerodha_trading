"""Pairs Trading / Statistical Arbitrage — market-neutral spread reversion.

Trades the spread between two instruments (A, B). The hedge ratio beta is
estimated by rolling OLS (or held static, or implied by a simple price
ratio); the spread is log(A) - beta*log(B) (or A/B). When the spread's
Z-score is stretched the strategy shorts the rich leg and buys the cheap
leg, targeting a return of the Z-score to zero. An optional Engle-Granger
style ADF gate refuses to trade a pair whose spread does not look stationary
on the data seen so far.

Not guaranteed profitable. Statistical relationships between two assets can
and do break down permanently; a "stop" on the spread is essential.
Validate out-of-sample.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import adf_tstat, rolling_beta, rolling_mean, rolling_std
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _OpenPair:
    side: str  # "long_spread" (long A / short B) | "short_spread"
    entry_index: int
    qty_a: int
    qty_b: int


class PairsTradingStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "pairs-trading"
    NAME: ClassVar[str] = "Pairs Trading / Statistical Arbitrage"
    CATEGORY: ClassVar[str] = "Statistical Arbitrage"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int] = 2

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "lookback": ParamSpec("integer", 60, "Window for the spread Z-score.", min=5, max=1000),
        "regression_window": ParamSpec("integer", 60, "Window for the rolling hedge-ratio OLS.",
                                       min=5, max=1000),
        "hedge_ratio_method": ParamSpec("enum", "rolling_ols", "How beta is estimated.",
                                        choices=("rolling_ols", "static", "price_ratio")),
        "entry_zscore": ParamSpec("number", 2.0, "Absolute spread Z-score to enter.",
                                  min=0.1, max=10.0),
        "exit_zscore": ParamSpec("number", 0.0, "Spread Z-score (toward 0) to exit.",
                                 min=0.0, max=10.0),
        "stop_zscore": ParamSpec("number", 3.5, "Spread Z-score beyond entry that force-exits "
                                 "(0 off).", min=0.0, max=20.0, group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 off).",
                                      min=0, max=100_000, group="risk"),
        "require_cointegration": ParamSpec("boolean", False,
                                           "Only trade while the spread passes the ADF gate.",
                                           group="filter"),
        "cointegration_lookback": ParamSpec("integer", 250,
                                            "History window (bars) for the ADF stationarity test.",
                                            min=30, max=2000, group="filter"),
        "adf_threshold": ParamSpec("number", -2.9,
                                   "Max ADF t-stat to consider the spread stationary "
                                   "(more negative = stricter).",
                                   min=-10.0, max=0.0, group="filter"),
        "min_spread_std": ParamSpec("number", 1e-6, "Skip when spread std is below this (degenerate).",
                                    min=0.0, max=1e6, group="filter"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "NRML", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            lookback=90, regression_window=90, hedge_ratio_method="rolling_ols",
            entry_zscore=2.5, exit_zscore=0.5, stop_zscore=4.0, require_cointegration=True,
            adf_threshold=-3.2, max_holding_bars=30, sizing_method="fixed_capital",
            max_position_size_pct=15.0,
        ),
        "balanced": preset(
            lookback=60, regression_window=60, hedge_ratio_method="rolling_ols",
            entry_zscore=2.0, exit_zscore=0.0, stop_zscore=3.5, require_cointegration=False,
            max_holding_bars=40, sizing_method="fixed_capital", max_position_size_pct=20.0,
        ),
        "aggressive": preset(
            lookback=40, regression_window=40, hedge_ratio_method="rolling_ols",
            entry_zscore=1.5, exit_zscore=0.0, stop_zscore=3.0, require_cointegration=False,
            max_holding_bars=25, sizing_method="fixed_capital", max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Market-neutral: trades the mean-reverting spread between two related instruments, "
            "long one leg and short the other, sized to be roughly value-neutral."
        ),
        logic=(
            "Estimate beta by rolling OLS of log(A) on log(B) (or static, or price ratio). Form "
            "spread = log(A) - beta*log(B). Z-score it over `lookback`. If require_cointegration is "
            "on, only trade while the spread's ADF t-stat is below adf_threshold. Enter short-spread "
            "(sell A / buy B) when Z >= entry_zscore, long-spread when Z <= -entry_zscore. Exit when "
            "Z reverts to +/- exit_zscore, runs past +/- stop_zscore, or after max_holding_bars."
        ),
        timeframe="day / 60minute / 15minute",
        market_types=["Pairs of related NSE equities (e.g. two large private banks)"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=True,
        complexity="High", time_horizon="Market-neutral",
        risks=[
            "Structural break: the historical relationship stops holding and the spread never "
            "reverts.",
            "Both legs move against you before the stop; short-leg borrow/again costs.",
            "Hedge-ratio instability makes the spread noisy and the Z-score unreliable.",
        ],
        best_for="Market-neutral books on economically-linked pairs with a stable ratio.",
        warning="Statistical relationships can break down.",
        required_data=[
            "Time-aligned OHLCV for both instruments",
            "at least max(lookback, regression_window) + a margin of overlapping bars",
        ],
        example=(
            "HDFCBANK / ICICIBANK, daily, lookback=60: when log(HDFCBANK) - beta*log(ICICIBANK) is "
            "2 sigma above its 60-day mean, sell HDFCBANK and buy ICICIBANK value-neutral; unwind "
            "when the Z-score returns to 0. Mechanics only, not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._pair: tuple[str, str] | None = None
        self._static_beta: float | None = None
        self._open: _OpenPair | None = None
        self._seen = 0

    def on_bar(self, bar: Bar) -> None:
        self.ingest(bar)
        self._seen += 1
        sym = bar.instrument

        if self._pair is None:
            syms = [s for s in self._buffers if s != sym]
            if syms:
                # deterministic ordering: first-seen is A
                first = next(iter(self._buffers))
                self._pair = (first, sym) if first != sym else (sym, syms[0])
        if self._pair is None:
            return
        a, b = self._pair
        buf_a, buf_b = self._buffers.get(a), self._buffers.get(b)
        if not buf_a or not buf_b:
            return

        # Only act once both legs have a bar for this step — otherwise the
        # "last" close of each buffer is misaligned in time.
        if len(buf_a.closes) != len(buf_b.closes):
            return

        n = int(self.p["lookback"])
        rw = int(self.p["regression_window"])
        coint_lb = int(self.p["cointegration_lookback"])
        min_need = max(n, rw) + 2
        hist = min(len(buf_a.closes), max(min_need, coint_lb + 2))
        if len(buf_a.closes) < min_need:
            return

        ca = list(buf_a.closes)[-hist:]
        cb = list(buf_b.closes)[-hist:]
        if any(x <= 0 for x in ca) or any(x <= 0 for x in cb):
            return
        la = [math.log(x) for x in ca]
        lb = [math.log(x) for x in cb]

        beta = self._beta(la, lb, rw)
        if beta is None:
            return

        if self.p["hedge_ratio_method"] == "price_ratio":
            spread_series = [ca[i] / cb[i] for i in range(len(ca))]
        else:
            spread_series = [la[i] - beta * lb[i] for i in range(len(la))]

        mean = rolling_mean(spread_series, n)
        std = rolling_std(spread_series, n)
        if mean is None or std is None or std <= float(self.p["min_spread_std"]):
            return
        z = (spread_series[-1] - mean) / std

        if self._open is not None:
            if self._should_exit(z):
                self._flatten(a, b)
            return

        if self.p["require_cointegration"]:
            t = adf_tstat(spread_series[-min(len(spread_series), coint_lb):])
            if t is None or t > float(self.p["adf_threshold"]):
                return

        price_a = buf_a.closes[-1]
        price_b = buf_b.closes[-1]
        if z >= float(self.p["entry_zscore"]):
            self._enter(a, b, "short_spread", price_a, price_b, beta)
        elif z <= -float(self.p["entry_zscore"]):
            self._enter(a, b, "long_spread", price_a, price_b, beta)

    # --- helpers -----------------------------------------------------

    def _beta(self, la: list[float], lb: list[float], rw: int) -> float | None:
        method = self.p["hedge_ratio_method"]
        if method == "price_ratio":
            return 1.0
        if method == "static":
            if self._static_beta is None:
                self._static_beta = rolling_beta(la[:rw], lb[:rw], rw)
            return self._static_beta
        return rolling_beta(la, lb, rw)

    def _leg_sizes(self, price_a: float, price_b: float, beta: float) -> tuple[int, int]:
        capital = float(self.p["capital_allocation"])
        per_leg = min(capital / 2.0, capital * float(self.p["max_position_size_pct"]) / 100.0)
        qty_a = int(per_leg // price_a) if price_a > 0 else 0
        if self.p["hedge_ratio_method"] == "price_ratio":
            qty_b = int(per_leg // price_b) if price_b > 0 else 0
        else:
            # value-neutral B leg
            qty_b = int(round(qty_a * price_a / price_b)) if price_b > 0 else 0
        return max(0, qty_a), max(0, qty_b)

    def _enter(self, a: str, b: str, side: str, price_a: float, price_b: float, beta: float) -> None:
        qty_a, qty_b = self._leg_sizes(price_a, price_b, beta)
        if qty_a <= 0 or qty_b <= 0:
            return
        ex, prod = self.p["exchange"], self.p["product"]
        if side == "short_spread":
            self.submit(a, "SELL", qty_a, exchange=ex, product=prod)
            self.submit(b, "BUY", qty_b, exchange=ex, product=prod)
        else:
            self.submit(a, "BUY", qty_a, exchange=ex, product=prod)
            self.submit(b, "SELL", qty_b, exchange=ex, product=prod)
        self._open = _OpenPair(side=side, entry_index=self._seen, qty_a=qty_a, qty_b=qty_b)

    def _should_exit(self, z: float) -> bool:
        assert self._open is not None
        ex = float(self.p["exit_zscore"])
        stop = float(self.p["stop_zscore"])
        if self._open.side == "short_spread":
            if z <= ex:
                return True
            if stop and z >= stop:
                return True
        else:
            if z >= -ex:
                return True
            if stop and z <= -stop:
                return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and (self._seen - self._open.entry_index) >= max_hold)

    def _flatten(self, a: str, b: str) -> None:
        self.rebalance_to(a, 0, exchange=self.p["exchange"], product=self.p["product"])
        self.rebalance_to(b, 0, exchange=self.p["exchange"], product=self.p["product"])
        self._open = None

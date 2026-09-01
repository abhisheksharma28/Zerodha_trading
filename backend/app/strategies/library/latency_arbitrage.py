"""Latency Arbitrage (lead-lag convergence) template.

IMPORTANT — this is NOT co-located, tick-level HFT latency arbitrage. This
platform runs on OHLCV bars over a single retail broker feed with
order-routing latency measured in tens of milliseconds at best, so any
genuine speed advantage is already gone before this strategy can act. What
this template actually implements is the retail-accessible cousin: a very
short-horizon *lead-lag* convergence trade. Given two tightly correlated
instruments (e.g. an index and its most liquid constituent, or the same
name on two exchanges), when the "leader" has moved and the "laggard" has
not yet caught up over the last few bars, it takes the laggard in the
leader's direction and exits as the return gap closes.

Not guaranteed profitable. At bar granularity the lead-lag edge is tiny and
usually smaller than costs; the two instruments can also simply decouple,
turning a "lag" into a real, non-reverting divergence. Validate
out-of-sample with a realistic cost model and treat the correlation guard
as mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import rolling_correlation
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _OpenPos:
    side: str  # "long" | "short" (of the laggard)
    entry_index: int
    entry_gap_bps: float


class LatencyArbitrageStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "latency-arbitrage"
    NAME: ClassVar[str] = "Latency Arbitrage (Lead-Lag)"
    CATEGORY: ClassVar[str] = "Arbitrage"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int] = 2

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "leader_symbol": ParamSpec("string", "",
                                   "Tradingsymbol of the leading instrument "
                                   "(blank = first-seen instrument is the leader).")
        ,
        "signal_lookback": ParamSpec("integer", 3,
                                     "Bars over which the leader vs laggard return gap is measured.",
                                     min=1, max=200),
        "divergence_bps": ParamSpec("number", 25.0,
                                    "Minimum leader-minus-laggard return gap (bps) to enter.",
                                    min=1.0, max=5000.0),
        "exit_gap_bps": ParamSpec("number", 5.0,
                                  "Close the position when the return gap narrows below this (bps).",
                                  min=0.0, max=5000.0, group="risk"),
        "stop_gap_bps": ParamSpec("number", 150.0,
                                  "Abandon when the gap instead widens past this (bps) — it was a "
                                  "real divergence, not a lag.", min=1.0, max=20000.0, group="risk"),
        "max_holding_bars": ParamSpec("integer", 5, "Force exit after N bars (0 off).",
                                      min=0, max=10_000, group="risk"),
        "corr_lookback": ParamSpec("integer", 60,
                                   "Window for the leader/laggard return-correlation guard.",
                                   min=5, max=1000, group="filter"),
        "min_correlation": ParamSpec("number", 0.7,
                                     "Skip entries when rolling return correlation is below this.",
                                     min=-1.0, max=1.0, group="filter"),
        "allow_short": ParamSpec("boolean", True,
                                 "Permit shorting the laggard when it has outrun the leader."),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "MIS", "Order product (short horizon => MIS).",
                             choices=("MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            signal_lookback=5, divergence_bps=40.0, exit_gap_bps=8.0, stop_gap_bps=120.0,
            max_holding_bars=4, corr_lookback=90, min_correlation=0.85, allow_short=False,
            sizing_method="fixed_capital", max_position_size_pct=10.0,
        ),
        "balanced": preset(
            signal_lookback=3, divergence_bps=25.0, exit_gap_bps=5.0, stop_gap_bps=150.0,
            max_holding_bars=5, corr_lookback=60, min_correlation=0.7, allow_short=True,
            sizing_method="fixed_quantity", fixed_quantity=1,
        ),
        "aggressive": preset(
            signal_lookback=2, divergence_bps=15.0, exit_gap_bps=3.0, stop_gap_bps=200.0,
            max_holding_bars=8, corr_lookback=40, min_correlation=0.55, allow_short=True,
            sizing_method="risk_per_trade", risk_per_trade_pct=0.5, max_position_size_pct=20.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Short-horizon lead-lag convergence between two tightly correlated instruments: takes "
            "the laggard in the leader's direction when it hasn't kept up, and exits as the gap "
            "closes. Not co-located HFT latency arbitrage."
        ),
        logic=(
            "Each bar, once both legs are time-aligned, measure the leader's and laggard's returns "
            "over signal_lookback bars. If the gap (leader minus laggard) exceeds divergence_bps and "
            "the rolling return correlation is at least min_correlation, trade the laggard in the "
            "direction of the gap. Exit when |gap| falls below exit_gap_bps (converged), rises above "
            "stop_gap_bps (real divergence), or after max_holding_bars."
        ),
        timeframe="1minute / 3minute (intraday only)",
        market_types=["Index vs its most liquid constituent", "dual-listed names (NSE/BSE)",
                      "an index and its ETF"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=False,
        supports_market_neutral=False,
        complexity="High", time_horizon="Intraday",
        risks=[
            "No real speed edge at retail latency / bar granularity — the modelled gap is often "
            "already arbitraged away.",
            "Decoupling: a 'lag' that is actually a permanent repricing never reverts.",
            "Transaction costs and slippage typically exceed the per-trade edge.",
        ],
        best_for="Research into intraday lead-lag structure on highly correlated pairs.",
        warning="Statistical relationships can break down, and any latency edge is likely gone.",
        required_data=["Time-aligned intraday OHLCV for both instruments",
                       "at least max(signal_lookback, corr_lookback) + 2 overlapping bars"],
        example=(
            "NIFTY 50 (leader) and NIFTYBEES (laggard) on 1-minute bars: if NIFTY is +30 bps over 3 "
            "minutes while NIFTYBEES is only +5 bps and their 60-bar return correlation is 0.9, buy "
            "NIFTYBEES and exit when the gap closes to 5 bps. Mechanics only, not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._pair: tuple[str, str] | None = None   # (leader, laggard)
        self._open: _OpenPos | None = None
        self._seen = 0

    def on_bar(self, bar: Bar) -> None:
        self.ingest(bar)
        self._seen += 1

        if self._pair is None and len(self._buffers) == 2:
            syms = list(self._buffers)
            leader = self.p["leader_symbol"] if self.p["leader_symbol"] in syms else syms[0]
            laggard = syms[1] if syms[0] == leader else syms[0]
            self._pair = (leader, laggard)
        if self._pair is None:
            return

        leader, laggard = self._pair
        lb, gb = self._buffers.get(leader), self._buffers.get(laggard)
        if not lb or not gb or len(lb.closes) != len(gb.closes):
            return

        sl = int(self.p["signal_lookback"])
        cl = int(self.p["corr_lookback"])
        if len(lb.closes) < max(sl, cl) + 2:
            return

        lead_c = list(lb.closes)
        lag_c = list(gb.closes)
        if lead_c[-1 - sl] <= 0 or lag_c[-1 - sl] <= 0:
            return
        lead_ret = lead_c[-1] / lead_c[-1 - sl] - 1.0
        lag_ret = lag_c[-1] / lag_c[-1 - sl] - 1.0
        gap_bps = (lead_ret - lag_ret) * 1e4

        if self._open is not None:
            if self._should_exit(gap_bps):
                self.rebalance_to(laggard, 0, exchange=self.p["exchange"],
                                  product=self.p["product"])
                self._open = None
            return

        lead_r = [lead_c[i] / lead_c[i - 1] - 1.0 for i in range(1, len(lead_c)) if lead_c[i - 1]]
        lag_r = [lag_c[i] / lag_c[i - 1] - 1.0 for i in range(1, len(lag_c)) if lag_c[i - 1]]
        corr = rolling_correlation(lead_r, lag_r, cl)
        if corr is None or corr < float(self.p["min_correlation"]):
            return

        if abs(gap_bps) < float(self.p["divergence_bps"]):
            return

        price = lag_c[-1]
        if gap_bps > 0:
            qty = self.size_position(price, symbol=laggard)
            if qty > 0:
                self.submit(laggard, "BUY", qty, exchange=self.p["exchange"],
                            product=self.p["product"])
                self._open = _OpenPos("long", self._seen, gap_bps)
        elif self.p["allow_short"]:
            qty = self.size_position(price, symbol=laggard)
            if qty > 0:
                self.submit(laggard, "SELL", qty, exchange=self.p["exchange"],
                            product=self.p["product"])
                self._open = _OpenPos("short", self._seen, gap_bps)

    def _should_exit(self, gap_bps: float) -> bool:
        assert self._open is not None
        if abs(gap_bps) <= float(self.p["exit_gap_bps"]):
            return True
        if abs(gap_bps) >= float(self.p["stop_gap_bps"]):
            return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and (self._seen - self._open.entry_index) >= max_hold)

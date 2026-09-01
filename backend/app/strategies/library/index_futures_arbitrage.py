"""Index / Futures Arbitrage (cash-futures basis) template.

Classic cash-and-carry: a future should trade at fair value
F* = S * exp((r - q) * T) where S is spot, r the risk-free rate, q the
dividend yield and T the time to expiry in years. When the observed future
is rich versus F* the strategy sells the future and buys the spot leg; when
it is cheap it does the reverse, holding until the basis converges (it must,
by expiry) or a model-error stop trips. It flattens a configurable number of
days before expiry.

Not guaranteed profitable. The edge is small and highly sensitive to
financing/borrow costs, the assumed rate and dividend yield, the inability
to always short the cash basket, futures-lot granularity, and margin. The
basis can also stay dislocated around events for longer than the position's
capital allows. Validate with a realistic Indian cost model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _OpenPos:
    side: str  # "future_rich" (short F / long S) | "future_cheap" (long F / short S)
    entry_index: int
    qty_future: int
    qty_spot: int


class IndexFuturesArbitrageStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "index-futures-arbitrage"
    NAME: ClassVar[str] = "Index / Futures Arbitrage"
    CATEGORY: ClassVar[str] = "Arbitrage"
    MIN_INSTRUMENTS: ClassVar[int] = 2
    MAX_INSTRUMENTS: ClassVar[int] = 2

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "spot_symbol": ParamSpec("string", "",
                                 "Tradingsymbol of the spot/cash leg "
                                 "(blank = first-seen instrument is spot; the other is the future)."),
        "risk_free_rate_pct": ParamSpec("number", 6.5, "Annualised risk-free rate (%).",
                                        min=0.0, max=50.0),
        "dividend_yield_pct": ParamSpec("number", 1.2, "Annualised dividend yield of the index (%).",
                                        min=0.0, max=20.0),
        "expiry_date": ParamSpec("string", "",
                                 "Futures expiry (YYYY-MM-DD, IST). Blank => use days_to_expiry."),
        "days_to_expiry": ParamSpec("integer", 30,
                                    "Fixed days to expiry when expiry_date is blank.",
                                    min=0, max=400),
        "entry_deviation_pct": ParamSpec("number", 0.35,
                                         "|future - fair value| as % of spot to enter.",
                                         min=0.0, max=20.0),
        "exit_deviation_pct": ParamSpec("number", 0.05,
                                        "Deviation (%) at which to unwind.", min=0.0, max=20.0,
                                        group="risk"),
        "stop_deviation_pct": ParamSpec("number", 2.0,
                                        "Deviation (%) that trips the model-error stop.",
                                        min=0.0, max=50.0, group="risk"),
        "futures_lot_size": ParamSpec("integer", 50,
                                      "Contract multiplier; future orders are rounded to this.",
                                      min=1, max=100_000),
        "close_days_before_expiry": ParamSpec("integer", 1,
                                              "Force flat this many days before expiry.",
                                              min=0, max=30, group="risk"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 off).",
                                      min=0, max=100_000, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange for the spot leg."),
        "futures_exchange": ParamSpec("string", "NFO", "Order exchange for the futures leg."),
        "product": ParamSpec("enum", "NRML", "Order product.", choices=("NRML", "MIS")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            entry_deviation_pct=0.5, exit_deviation_pct=0.05, stop_deviation_pct=1.5,
            close_days_before_expiry=2, sizing_method="fixed_capital", max_position_size_pct=15.0,
        ),
        "balanced": preset(
            entry_deviation_pct=0.35, exit_deviation_pct=0.05, stop_deviation_pct=2.0,
            close_days_before_expiry=1, sizing_method="fixed_capital", max_position_size_pct=20.0,
        ),
        "aggressive": preset(
            entry_deviation_pct=0.2, exit_deviation_pct=0.03, stop_deviation_pct=3.0,
            close_days_before_expiry=1, sizing_method="fixed_capital", max_position_size_pct=25.0,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Cash-and-carry basis trade: sells the rich leg and buys the cheap leg when the future "
            "deviates from its carry-model fair value, holding until the basis converges."
        ),
        logic=(
            "Each aligned bar compute fair value F* = S * exp((r - q) * T) with T from expiry_date "
            "(or days_to_expiry). Deviation = (F - F*) / S. If deviation >= entry_deviation_pct the "
            "future is rich: SELL the future / BUY spot. If <= -entry_deviation_pct: BUY the future "
            "/ SELL spot. Unwind when |deviation| <= exit_deviation_pct, when it exceeds "
            "stop_deviation_pct, at max_holding_bars, or close_days_before_expiry."
        ),
        timeframe="day / 15minute",
        market_types=["Index spot (or its ETF) vs the corresponding index future",
                      "single-stock cash vs stock future"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=True,
        complexity="High", time_horizon="Market-neutral",
        risks=[
            "Financing / stock-borrow cost can exceed the captured basis.",
            "Wrong rate or dividend assumption biases every signal.",
            "Cannot always short the cash basket; futures lot size forces imperfect hedges.",
            "Basis can widen further around expiry, dividends or index rebalancing before it "
            "converges.",
        ],
        best_for="Market-neutral capture of futures mispricing when both legs are cheaply tradeable.",
        warning="Statistical relationships can break down; carry assumptions may be wrong.",
        required_data=["Time-aligned OHLCV for the spot and futures legs",
                       "a correct expiry date (or days_to_expiry) and carry inputs"],
        example=(
            "NIFTY spot at 24,000 with the current-month future at 24,120, r=6.5%, q=1.2%, 20 days "
            "to expiry: fair value ~24,070, so the future is ~0.2% rich -> sell the future, buy the "
            "spot leg, unwind as they converge. Mechanics only, not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._pair: tuple[str, str] | None = None  # (spot, future)
        self._open: _OpenPos | None = None
        self._seen = 0

    def _years_to_expiry(self, bar: Bar) -> float:
        exp = str(self.p["expiry_date"]).strip()
        if exp:
            try:
                exp_d = date.fromisoformat(exp)
            except ValueError:
                exp_d = None
            if exp_d is not None:
                days = (exp_d - self.bar_dt(bar).date()).days
                return max(0.0, days) / 365.0
        return max(0, int(self.p["days_to_expiry"])) / 365.0

    def _days_to_expiry(self, bar: Bar) -> int | None:
        exp = str(self.p["expiry_date"]).strip()
        if not exp:
            return None
        try:
            return (date.fromisoformat(exp) - self.bar_dt(bar).date()).days
        except ValueError:
            return None

    def on_bar(self, bar: Bar) -> None:
        self.ingest(bar)
        self._seen += 1

        if self._pair is None and len(self._buffers) == 2:
            syms = list(self._buffers)
            spot = self.p["spot_symbol"] if self.p["spot_symbol"] in syms else syms[0]
            future = syms[1] if syms[0] == spot else syms[0]
            self._pair = (spot, future)
        if self._pair is None:
            return

        spot, future = self._pair
        sb, fb = self._buffers.get(spot), self._buffers.get(future)
        if not sb or not fb or len(sb.closes) != len(fb.closes) or not sb.closes:
            return

        s = sb.closes[-1]
        f = fb.closes[-1]
        if s <= 0 or f <= 0:
            return
        r = float(self.p["risk_free_rate_pct"]) / 100.0
        q = float(self.p["dividend_yield_pct"]) / 100.0
        t = self._years_to_expiry(bar)
        fair = s * math.exp((r - q) * t)
        dev_pct = (f - fair) / s * 100.0

        dte = self._days_to_expiry(bar)
        near_expiry = dte is not None and dte <= int(self.p["close_days_before_expiry"])

        if self._open is not None:
            if near_expiry or self._should_exit(dev_pct):
                self.rebalance_to(spot, 0, exchange=self.p["exchange"], product=self.p["product"])
                self.rebalance_to(future, 0, exchange=self.p["futures_exchange"],
                                  product=self.p["product"])
                self._open = None
            return

        if near_expiry:
            return

        entry = float(self.p["entry_deviation_pct"])
        if abs(dev_pct) < entry:
            return

        lot = int(self.p["futures_lot_size"])
        raw = self.size_position(f, symbol=future)
        qty_f = (raw // lot) * lot
        if qty_f <= 0:
            return
        qty_s = qty_f  # 1:1 point exposure between the legs

        if dev_pct >= entry:  # future rich
            self.submit(future, "SELL", qty_f, exchange=self.p["futures_exchange"],
                        product=self.p["product"])
            self.submit(spot, "BUY", qty_s, exchange=self.p["exchange"], product=self.p["product"])
            self._open = _OpenPos("future_rich", self._seen, qty_f, qty_s)
        else:  # future cheap
            self.submit(future, "BUY", qty_f, exchange=self.p["futures_exchange"],
                        product=self.p["product"])
            self.submit(spot, "SELL", qty_s, exchange=self.p["exchange"], product=self.p["product"])
            self._open = _OpenPos("future_cheap", self._seen, qty_f, qty_s)

    def _should_exit(self, dev_pct: float) -> bool:
        assert self._open is not None
        if abs(dev_pct) <= float(self.p["exit_deviation_pct"]):
            return True
        if abs(dev_pct) >= float(self.p["stop_deviation_pct"]):
            return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and (self._seen - self._open.entry_index) >= max_hold)

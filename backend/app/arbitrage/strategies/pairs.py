"""Pairs Trading / Statistical Arbitrage (2-leg, market-neutral).

Classified STATISTICAL_ARBITRAGE — not risk-free. The spread between two
related instruments mean-reverts *until the relationship breaks*, which it
eventually does; the Z-score stop is not optional.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, ClassVar

from app.arbitrage.base import ArbitrageStrategy, ArbSpec
from app.arbitrage.data_sync import SyncedPoint
from app.arbitrage.types import ArbCategory, TradeStructure
from app.strategies.indicators import adf_tstat, rolling_beta, rolling_mean, rolling_std
from app.strategies.library.base import ParamSpec, preset


def _half_life(spread: list[float]) -> float:
    if len(spread) < 20:
        return 10.0
    lag = spread[:-1]
    delta = [spread[i] - spread[i - 1] for i in range(1, len(spread))]
    n = len(delta)
    mx = sum(lag) / n
    my = sum(delta) / n
    sxx = sum((x - mx) ** 2 for x in lag)
    if sxx <= 0:
        return 10.0
    b = sum((lag[i] - mx) * (delta[i] - my) for i in range(n)) / sxx
    if b >= 0 or (1 + b) <= 0:
        return 60.0
    return max(1.0, min(120.0, -math.log(2) / math.log(1 + b)))


class PairsArbitrageStrategy(ArbitrageStrategy):
    N_LEGS: ClassVar[int] = 2

    SPEC: ClassVar[ArbSpec] = ArbSpec(
        slug="pairs-arb",
        name="Pairs Trading / Statistical Arbitrage",
        category=ArbCategory.STATISTICAL_ARBITRAGE,
        description=(
            "Market-neutral. Trades the Z-score of the spread between two related instruments, "
            "shorting the rich leg and buying the cheap leg, targeting reversion to the mean."
        ),
        logic=(
            "Rolling-OLS hedge ratio beta of log(A) on log(B); spread = log(A) - beta*log(B); "
            "Z-score over `lookback`. Enter when |Z| >= entry_zscore, exit toward |Z| <= "
            "exit_zscore, stop at |Z| >= stop_zscore, force-converge after max_holding_days, and "
            "(optional) bail on ADF-gate failure = model breakdown."
        ),
        legs="2 equities, dollar-weighted market-neutral",
        data_requirements=["daily or intraday OHLCV for both legs", "aligned timestamps"],
        latency_sensitivity="low",
        min_net_edge_bps_default=15.0,
        infra_note="retail-viable on daily/60m bars; not a true arbitrage",
        warning="Statistical relationships break down permanently — the Z-score stop is essential.",
        supported_timeframes=("1d", "60m", "30m"),
    )

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "lookback": ParamSpec("integer", 60, "Window for the spread Z-score.", min=10, max=1000),
        "regression_window": ParamSpec("integer", 60, "Window for the rolling hedge-ratio OLS.",
                                       min=10, max=1000),
        "entry_zscore": ParamSpec("number", 2.0, "Absolute spread Z to enter.", min=0.5, max=10.0),
        "exit_zscore": ParamSpec("number", 0.3, "Spread Z (toward 0) to exit.", min=0.0, max=10.0),
        "stop_zscore": ParamSpec("number", 3.5, "Spread Z beyond which to force-exit.",
                                 min=0.5, max=20.0, group="risk"),
        "require_cointegration": ParamSpec("boolean", True,
                                           "Only hold while the spread passes an ADF gate.",
                                           group="filter"),
        "adf_threshold": ParamSpec("number", -2.9, "Max ADF t-stat to call the spread stationary.",
                                   min=-10.0, max=0.0, group="filter"),
        "coint_lookback": ParamSpec("integer", 250, "Bars used for the ADF gate.",
                                    min=30, max=2000, group="filter"),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(lookback=90, regression_window=90, entry_zscore=2.5,
                               exit_zscore=0.5, stop_zscore=4.0, require_cointegration=True,
                               adf_threshold=-3.2, max_holding_days=25, min_net_edge_bps=25.0),
        "balanced": preset(lookback=60, regression_window=60, entry_zscore=2.0, exit_zscore=0.3,
                           stop_zscore=3.5, require_cointegration=True, adf_threshold=-2.9,
                           max_holding_days=30, min_net_edge_bps=15.0),
        "aggressive": preset(lookback=40, regression_window=40, entry_zscore=1.5, exit_zscore=0.0,
                             stop_zscore=3.0, require_cointegration=False, max_holding_days=20,
                             min_net_edge_bps=8.0),
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        m = max(int(self.p["lookback"]), int(self.p["regression_window"]),
                int(self.p["coint_lookback"])) + 5
        self._la: deque[float] = deque(maxlen=m)
        self._lb: deque[float] = deque(maxlen=m)
        self._spread: deque[float] = deque(maxlen=m)
        self._syms: list[str] = []
        self._z = 0.0
        self._beta = 1.0
        self._adf: float | None = None

    def _on_point(self, point: SyncedPoint) -> None:
        if not self._syms:
            self._syms = list(point.bars)
        a, b = self._syms
        pa, pb = point.bars[a].close, point.bars[b].close
        if pa <= 0 or pb <= 0:
            return
        self._la.append(math.log(pa))
        self._lb.append(math.log(pb))
        rw = int(self.p["regression_window"])
        if len(self._la) >= rw:
            beta = rolling_beta(list(self._la), list(self._lb), rw)
            self._beta = beta if beta and abs(beta) < 20 else self._beta
        self._spread.append(self._la[-1] - self._beta * self._lb[-1])
        lb = int(self.p["lookback"])
        if len(self._spread) >= lb:
            mu = rolling_mean(list(self._spread), lb) or 0.0
            sd = rolling_std(list(self._spread), lb) or 0.0
            self._z = (self._spread[-1] - mu) / sd if sd > 1e-9 else 0.0
        clb = int(self.p["coint_lookback"])
        if len(self._spread) >= clb:
            self._adf = adf_tstat(list(self._spread)[-clb:])

    def _coint_ok(self) -> bool:
        if not self.p["require_cointegration"]:
            return True
        return self._adf is not None and self._adf <= float(self.p["adf_threshold"])

    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        if len(self._spread) < int(self.p["lookback"]) or len(self._syms) < 2:
            return None
        if abs(self._z) < float(self.p["entry_zscore"]) or not self._coint_ok():
            return None
        sd = rolling_std(list(self._spread), int(self.p["lookback"])) or 0.0
        direction = "short_spread" if self._z > 0 else "long_spread"
        return {
            "direction": direction,
            "zscore": round(self._z, 3),
            "hedge_ratio": round(self._beta, 6),
            "adf_tstat": round(self._adf, 3) if self._adf is not None else None,
            "spread_std": round(sd, 6),
            # convergence to the mean ~ |z|*sd of fractional spread -> bps of the A leg
            "gross_edge_bps": round(abs(self._z) * sd * 1e4, 2),
            "expected_holding_days": round(_half_life(list(self._spread)), 1),
        }

    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        a, b = self._syms
        pa, pb = point.bars[a].close, point.bars[b].close
        cap = float(self.p["capital"]) * float(self.p["position_fraction"])
        beta = abs(float(signal["hedge_ratio"])) or 1.0
        # split capital so |notional_A| ~ |notional_B| (beta-weighted), gross <= cap
        qa = int(cap / (pa * (1.0 + beta)))
        qb = int(qa * pa * beta / pb) if pb > 0 else 0
        if qa <= 0 or qb <= 0:
            return None
        short_a = signal["direction"] == "short_spread"
        legs = [
            self._leg(a, "SELL" if short_a else "BUY", 1.0, pa, quantity=qa, segment="equity",
                      borrow_required=short_a),
            self._leg(b, "BUY" if short_a else "SELL", beta, pb, quantity=qb, segment="equity",
                      borrow_required=not short_a),
        ]
        notional = qa * pa + qb * pb
        return TradeStructure(
            legs=legs, direction=signal["direction"], hedge_ratio=beta,
            notional_per_unit=notional, capital_required=notional,
            margin_required=notional * 0.25,  # MIS-style span+exposure rough
            expected_holding_days=float(signal["expected_holding_days"]),
        )

    def check_exit(self, point: SyncedPoint) -> tuple[bool, str]:
        if self.open is None:
            return False, ""
        held = self._i - self.open.entry_index
        max_days = int(self.p["max_holding_days"])
        if abs(self._z) <= float(self.p["exit_zscore"]):
            return True, "converged"
        if abs(self._z) >= float(self.p["stop_zscore"]):
            return True, "stop_zscore"
        if self.p["require_cointegration"] and not self._coint_ok():
            return True, "model_breakdown"
        if max_days and held >= max_days:
            return True, "max_holding_days"
        return False, ""

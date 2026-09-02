"""Index / Futures Basis Arbitrage (2-leg, BASIS_ARBITRAGE).

Trades the mean reversion of the basis between an index (or an index-ETF
proxy) and its near future. Fair value = spot * (1 + (r - q) * t); the
tradeable signal is the Z-score of (actual basis - fair basis).
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from app.arbitrage.base import ArbitrageStrategy, ArbSpec
from app.arbitrage.data_sync import SyncedPoint
from app.arbitrage.strategies._basis import BASIS_COMMON, days_to_expiry
from app.arbitrage.types import ArbCategory, TradeStructure
from app.strategies.indicators import rolling_mean, rolling_std
from app.strategies.library.base import ParamSpec, preset


class IndexFuturesBasisStrategy(ArbitrageStrategy):
    N_LEGS: ClassVar[int] = 2

    SPEC: ClassVar[ArbSpec] = ArbSpec(
        slug="index-futures-basis",
        name="Index / Futures Basis Arbitrage",
        category=ArbCategory.BASIS_ARBITRAGE,
        description=(
            "Long/short the index future versus a spot proxy when the basis deviates from its "
            "cost-of-carry fair value, targeting reversion (and full convergence at expiry)."
        ),
        logic=(
            "fair_basis = spot * (r - q) * days_to_expiry/365. residual = (future - spot) - "
            "fair_basis. Z-score the residual over `lookback`. Enter |Z| >= entry_zscore (sell the "
            "future if rich, buy if cheap), exit |Z| <= exit_zscore, stop |Z| >= stop_zscore, "
            "force-close close_days_before_expiry."
        ),
        legs="index-ETF / spot proxy + the index near future",
        data_requirements=["aligned spot-proxy and index-future OHLCV", "near expiry date",
                           "risk-free rate + dividend yield"],
        latency_sensitivity="medium",
        min_net_edge_bps_default=15.0,
        infra_note="needs verified index-future historical data for a multi-expiry backtest",
        warning="The spot proxy is not the index; tracking error and ETF liquidity add basis risk "
        "the model does not price.",
        supported_timeframes=("1d", "60m"),
    )

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        **BASIS_COMMON,
        "risk_free_rate": ParamSpec("number", 0.068, "Annual risk-free rate for fair basis.",
                                    min=0.0, max=0.3),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(lookback=60, entry_zscore=2.5, exit_zscore=0.5, stop_zscore=4.0,
                               close_days_before_expiry=3, max_holding_days=20,
                               min_net_edge_bps=25.0, position_fraction=0.4),
        "balanced": preset(lookback=40, entry_zscore=2.0, exit_zscore=0.3, stop_zscore=4.0,
                           close_days_before_expiry=2, max_holding_days=15, min_net_edge_bps=15.0,
                           position_fraction=0.5),
        "aggressive": preset(lookback=25, entry_zscore=1.5, exit_zscore=0.0, stop_zscore=3.0,
                             close_days_before_expiry=1, max_holding_days=10, min_net_edge_bps=8.0,
                             position_fraction=0.6),
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        m = int(self.p["lookback"]) + 5
        self._resid: deque[float] = deque(maxlen=m)
        self._syms: list[str] = []
        self._spot = 0.0
        self._fut = 0.0
        self._z = 0.0
        self._dte = 30.0

    def _on_point(self, point: SyncedPoint) -> None:
        if not self._syms:
            self._syms = list(point.bars)
        s, f = self._syms
        self._spot = point.bars[s].close
        self._fut = point.bars[f].close
        if self._spot <= 0:
            return
        self._dte = max(0.5, days_to_expiry(point, float(self.p["expiry_ts"])))
        carry = float(self.p["risk_free_rate"]) - float(self.p["dividend_yield_annual"])
        fair_basis = self._spot * carry * self._dte / 365.0
        residual = (self._fut - self._spot) - fair_basis
        self._resid.append(residual)
        lb = int(self.p["lookback"])
        if len(self._resid) >= lb:
            mu = rolling_mean(list(self._resid), lb) or 0.0
            sd = rolling_std(list(self._resid), lb) or 0.0
            self._z = (residual - mu) / sd if sd > 1e-9 else 0.0

    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        if len(self._resid) < int(self.p["lookback"]) or len(self._syms) < 2:
            return None
        if self._dte <= float(self.p["close_days_before_expiry"]):
            return None
        if abs(self._z) < float(self.p["entry_zscore"]):
            return None
        sd = rolling_std(list(self._resid), int(self.p["lookback"])) or 0.0
        return {
            "direction": "sell_future" if self._z > 0 else "buy_future",
            "zscore": round(self._z, 3),
            "residual": round(self._resid[-1], 4),
            "days_to_expiry": round(self._dte, 1),
            "hedge_ratio": 1.0,
            "gross_edge_bps": round(abs(self._z) * sd / self._spot * 1e4, 2),
            "expected_holding_days": round(min(self._dte, 15.0), 1),
        }

    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        s, f = self._syms
        ps, pf = self._spot, self._fut
        cap = float(self.p["capital"]) * float(self.p["position_fraction"])
        q = int(cap / (ps + pf))
        if q <= 0:
            return None
        sell_fut = signal["direction"] == "sell_future"
        legs = [
            self._leg(s, "BUY" if sell_fut else "SELL", 1.0, ps, quantity=q, segment="equity",
                      product="CNC", borrow_required=not sell_fut),
            self._leg(f, "SELL" if sell_fut else "BUY", 1.0, pf, quantity=q, segment="futures",
                      exchange="NFO", product="NRML"),
        ]
        notional = q * (ps + pf)
        return TradeStructure(
            legs=legs, direction=signal["direction"], hedge_ratio=1.0,
            notional_per_unit=notional, capital_required=q * ps + q * pf * 0.12,
            margin_required=q * pf * 0.12,
            expected_holding_days=float(signal["expected_holding_days"]),
        )

    def check_exit(self, point: SyncedPoint) -> tuple[bool, str]:
        if self.open is None:
            return False, ""
        if self._dte <= float(self.p["close_days_before_expiry"]):
            return True, "expiry_close"
        if abs(self._z) <= float(self.p["exit_zscore"]):
            return True, "converged"
        if abs(self._z) >= float(self.p["stop_zscore"]):
            return True, "stop_zscore"
        max_days = int(self.p["max_holding_days"])
        if max_days and (self._i - self.open.entry_index) >= max_days:
            return True, "max_holding_days"
        return False, ""

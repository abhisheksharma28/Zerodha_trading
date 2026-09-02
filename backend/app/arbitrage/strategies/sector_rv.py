"""Sector Relative Value (2-leg).

RELATIVE_VALUE — a *view* that a stock is rich/cheap versus a sector proxy
(a peer, a sector ETF, or a sector index tradable). It is NOT market- or
sector-neutral in the cointegration sense: directional and sector risk
remain, so the Z-score stop and the holding cap do real work.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, ClassVar

from app.arbitrage.base import ArbitrageStrategy, ArbSpec
from app.arbitrage.data_sync import SyncedPoint
from app.arbitrage.strategies.pairs import _half_life
from app.arbitrage.types import ArbCategory, TradeStructure
from app.strategies.indicators import rolling_beta, rolling_mean, rolling_std
from app.strategies.library.base import ParamSpec, preset


class SectorRelativeValueStrategy(ArbitrageStrategy):
    N_LEGS: ClassVar[int] = 2

    SPEC: ClassVar[ArbSpec] = ArbSpec(
        slug="sector-rv",
        name="Sector Relative Value",
        category=ArbCategory.RELATIVE_VALUE,
        description=(
            "Long the cheap name / short the sector proxy (or vice versa) when the stock's "
            "valuation ratio to its sector is stretched, targeting reversion of the ratio."
        ),
        logic=(
            "spread = log(stock) - beta*log(proxy), beta by rolling OLS or fixed at 1 (ratio). "
            "Z-score over `lookback`. Enter |Z| >= entry_zscore, exit toward |Z| <= exit_zscore, "
            "stop |Z| >= stop_zscore, force-exit after max_holding_days. No cointegration gate — "
            "this is a relative-value view, not statistical arbitrage."
        ),
        legs="stock vs a sector proxy (peer / sector ETF / sector index)",
        data_requirements=["daily or 60m OHLCV for the stock and the proxy", "aligned timestamps"],
        latency_sensitivity="low",
        min_net_edge_bps_default=20.0,
        infra_note="retail-viable; carries residual sector and single-name risk",
        warning="Relative value is a directional bet that a gap closes — it may widen for a long "
                "time or not close at all.",
        supported_timeframes=("1d", "60m"),
    )

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "beta_method": ParamSpec("enum", "rolling_ols", "How the proxy hedge ratio is set.",
                                 choices=("ratio", "rolling_ols")),
        "regression_window": ParamSpec("integer", 90, "Rolling-OLS window.", min=20, max=1000),
        "lookback": ParamSpec("integer", 60, "Spread Z-score window.", min=10, max=1000),
        "entry_zscore": ParamSpec("number", 2.0, "Absolute Z to enter.", min=0.5, max=10.0),
        "exit_zscore": ParamSpec("number", 0.4, "Z (toward 0) to exit.", min=0.0, max=10.0),
        "stop_zscore": ParamSpec("number", 3.0, "Z beyond which to force-exit.",
                                 min=0.5, max=20.0, group="risk"),
        "min_correlation": ParamSpec("number", 0.5,
                                     "Skip if trailing return correlation with the proxy < this.",
                                     min=0.0, max=1.0, group="filter"),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(beta_method="rolling_ols", regression_window=120, lookback=90,
                               entry_zscore=2.5, exit_zscore=0.6, stop_zscore=3.5,
                               min_correlation=0.65, max_holding_days=30, min_net_edge_bps=30.0,
                               position_fraction=0.35),
        "balanced": preset(beta_method="rolling_ols", regression_window=90, lookback=60,
                           entry_zscore=2.0, exit_zscore=0.4, stop_zscore=3.0, min_correlation=0.5,
                           max_holding_days=25, min_net_edge_bps=20.0, position_fraction=0.5),
        "aggressive": preset(beta_method="ratio", lookback=40, entry_zscore=1.5, exit_zscore=0.0,
                             stop_zscore=2.5, min_correlation=0.35, max_holding_days=20,
                             min_net_edge_bps=12.0, position_fraction=0.6),
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        m = max(int(self.p["lookback"]), int(self.p["regression_window"])) + 5
        self._ls: deque[float] = deque(maxlen=m)   # log stock
        self._lp: deque[float] = deque(maxlen=m)   # log proxy
        self._spread: deque[float] = deque(maxlen=m)
        self._syms: list[str] = []
        self._z = 0.0
        self._beta = 1.0

    def _on_point(self, point: SyncedPoint) -> None:
        if not self._syms:
            self._syms = list(point.bars)
        s, p = self._syms
        ps, pp = point.bars[s].close, point.bars[p].close
        if ps <= 0 or pp <= 0:
            return
        self._ls.append(math.log(ps))
        self._lp.append(math.log(pp))
        if self.p["beta_method"] == "rolling_ols":
            rw = int(self.p["regression_window"])
            if len(self._ls) >= rw:
                bt = rolling_beta(list(self._ls), list(self._lp), rw)
                if bt and abs(bt) < 20:
                    self._beta = bt
        else:
            self._beta = 1.0
        self._spread.append(self._ls[-1] - self._beta * self._lp[-1])
        lb = int(self.p["lookback"])
        if len(self._spread) >= lb:
            mu = rolling_mean(list(self._spread), lb) or 0.0
            sd = rolling_std(list(self._spread), lb) or 0.0
            self._z = (self._spread[-1] - mu) / sd if sd > 1e-9 else 0.0

    def _corr_ok(self) -> bool:
        lb = int(self.p["lookback"])
        if len(self._ls) < lb + 2:
            return False
        rs = [self._ls[i] - self._ls[i - 1] for i in range(len(self._ls) - lb, len(self._ls))]
        rp = [self._lp[i] - self._lp[i - 1] for i in range(len(self._lp) - lb, len(self._lp))]
        n = len(rs)
        ms, mp = sum(rs) / n, sum(rp) / n
        cov = sum((rs[i] - ms) * (rp[i] - mp) for i in range(n))
        ss = math.sqrt(sum((v - ms) ** 2 for v in rs) * sum((v - mp) ** 2 for v in rp))
        corr = cov / ss if ss > 0 else 0.0
        return corr >= float(self.p["min_correlation"])

    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        if len(self._spread) < int(self.p["lookback"]) or len(self._syms) < 2:
            return None
        if abs(self._z) < float(self.p["entry_zscore"]) or not self._corr_ok():
            return None
        sd = rolling_std(list(self._spread), int(self.p["lookback"])) or 0.0
        return {
            "direction": "short_spread" if self._z > 0 else "long_spread",
            "zscore": round(self._z, 3),
            "hedge_ratio": round(self._beta, 6),
            "gross_edge_bps": round(abs(self._z) * sd * 1e4, 2),
            "expected_holding_days": round(_half_life(list(self._spread)), 1),
        }

    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        s, p = self._syms
        ps, pp = point.bars[s].close, point.bars[p].close
        cap = float(self.p["capital"]) * float(self.p["position_fraction"])
        beta = abs(float(signal["hedge_ratio"])) or 1.0
        qs = int(cap / (ps * (1.0 + beta)))
        qp = int(qs * ps * beta / pp) if pp > 0 else 0
        if qs <= 0 or qp <= 0:
            return None
        short_s = signal["direction"] == "short_spread"
        legs = [
            self._leg(s, "SELL" if short_s else "BUY", 1.0, ps, quantity=qs, segment="equity",
                      borrow_required=short_s),
            self._leg(p, "BUY" if short_s else "SELL", beta, pp, quantity=qp, segment="equity",
                      borrow_required=not short_s),
        ]
        notional = qs * ps + qp * pp
        return TradeStructure(
            legs=legs, direction=signal["direction"], hedge_ratio=beta,
            notional_per_unit=notional, capital_required=notional,
            margin_required=notional * 0.25,
            expected_holding_days=float(signal["expected_holding_days"]),
        )

    def check_exit(self, point: SyncedPoint) -> tuple[bool, str]:
        if self.open is None:
            return False, ""
        if abs(self._z) <= float(self.p["exit_zscore"]):
            return True, "converged"
        if abs(self._z) >= float(self.p["stop_zscore"]):
            return True, "stop_zscore"
        max_days = int(self.p["max_holding_days"])
        if max_days and (self._i - self.open.entry_index) >= max_days:
            return True, "max_holding_days"
        return False, ""

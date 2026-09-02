"""Futures Calendar Spread Arbitrage (2-leg, BASIS_ARBITRAGE).

Trades the mean reversion of the near-vs-far futures spread (the carry
between two expiries of the same underlying). Roll / close before the near
contract expires.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from app.arbitrage.base import ArbitrageStrategy, ArbSpec
from app.arbitrage.data_sync import SyncedPoint
from app.arbitrage.strategies._basis import days_to_expiry
from app.arbitrage.types import ArbCategory, TradeStructure
from app.strategies.indicators import rolling_mean, rolling_std
from app.strategies.library.base import ParamSpec, preset


class CalendarSpreadStrategy(ArbitrageStrategy):
    N_LEGS: ClassVar[int] = 2

    SPEC: ClassVar[ArbSpec] = ArbSpec(
        slug="calendar-spread",
        name="Futures Calendar Spread Arbitrage",
        category=ArbCategory.BASIS_ARBITRAGE,
        description=(
            "Long/short the far future versus the near future when the calendar spread "
            "(the inter-month carry) is stretched versus its recent range, targeting reversion."
        ),
        logic=(
            "spread = far - near. annualised = spread/near * 365 / (far_dte - near_dte). Z-score "
            "the spread over `lookback`. Enter |Z| >= entry_zscore (sell far / buy near if the "
            "spread is rich, mirror if cheap), exit |Z| <= exit_zscore, stop |Z| >= stop_zscore, "
            "roll/close near_close_days before the NEAR expiry."
        ),
        legs="near future + far future of the same underlying",
        data_requirements=["aligned near-future and far-future OHLCV", "both expiry dates"],
        latency_sensitivity="medium",
        min_net_edge_bps_default=12.0,
        infra_note="needs verified multi-expiry F&O historical data for a backtest",
        warning="A calendar spread is not delta-neutral to the term structure — a shift in the "
        "curve's shape moves it even when the underlying is flat.",
        supported_timeframes=("1d",),
    )

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "near_expiry_ts": ParamSpec("number", 0.0, "Epoch seconds of the NEAR expiry (0 = 30d).",
                                    min=0.0),
        "far_expiry_ts": ParamSpec("number", 0.0, "Epoch seconds of the FAR expiry (0 = 60d).",
                                   min=0.0),
        "lookback": ParamSpec("integer", 40, "Rolling Z-score window.", min=10, max=1000),
        "entry_zscore": ParamSpec("number", 2.0, "Absolute Z to enter.", min=0.3, max=10.0),
        "exit_zscore": ParamSpec("number", 0.3, "Z (toward 0) to exit.", min=0.0, max=10.0),
        "stop_zscore": ParamSpec("number", 4.0, "Z beyond which to force-exit.",
                                 min=0.5, max=20.0, group="risk"),
        "near_close_days": ParamSpec("integer", 3, "Close/roll this many days before near expiry.",
                                     min=0, max=30, group="risk"),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(lookback=60, entry_zscore=2.5, exit_zscore=0.5, stop_zscore=4.0,
                               near_close_days=5, max_holding_days=20, min_net_edge_bps=20.0,
                               position_fraction=0.4),
        "balanced": preset(lookback=40, entry_zscore=2.0, exit_zscore=0.3, stop_zscore=4.0,
                           near_close_days=3, max_holding_days=15, min_net_edge_bps=12.0,
                           position_fraction=0.5),
        "aggressive": preset(lookback=25, entry_zscore=1.5, exit_zscore=0.0, stop_zscore=3.0,
                             near_close_days=2, max_holding_days=10, min_net_edge_bps=6.0,
                             position_fraction=0.6),
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        m = int(self.p["lookback"]) + 5
        self._spread: deque[float] = deque(maxlen=m)
        self._syms: list[str] = []
        self._near = 0.0
        self._far = 0.0
        self._z = 0.0
        self._near_dte = 30.0

    def _on_point(self, point: SyncedPoint) -> None:
        if not self._syms:
            self._syms = list(point.bars)
        n, f = self._syms
        self._near = point.bars[n].close
        self._far = point.bars[f].close
        self._spread.append(self._far - self._near)
        self._near_dte = max(0.5, days_to_expiry(point, float(self.p["near_expiry_ts"])))
        lb = int(self.p["lookback"])
        if len(self._spread) >= lb:
            mu = rolling_mean(list(self._spread), lb) or 0.0
            sd = rolling_std(list(self._spread), lb) or 0.0
            self._z = (self._spread[-1] - mu) / sd if sd > 1e-9 else 0.0

    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        if len(self._spread) < int(self.p["lookback"]) or len(self._syms) < 2 or self._near <= 0:
            return None
        if self._near_dte <= float(self.p["near_close_days"]):
            return None
        if abs(self._z) < float(self.p["entry_zscore"]):
            return None
        sd = rolling_std(list(self._spread), int(self.p["lookback"])) or 0.0
        return {
            "direction": "sell_far" if self._z > 0 else "buy_far",
            "zscore": round(self._z, 3),
            "spread": round(self._far - self._near, 4),
            "near_days_to_expiry": round(self._near_dte, 1),
            "hedge_ratio": 1.0,
            "gross_edge_bps": round(abs(self._z) * sd / self._near * 1e4, 2),
            "expected_holding_days": round(min(self._near_dte, 15.0), 1),
        }

    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        n, f = self._syms
        pn, pf = self._near, self._far
        cap = float(self.p["capital"]) * float(self.p["position_fraction"])
        q = int(cap / (pn + pf))
        if q <= 0:
            return None
        sell_far = signal["direction"] == "sell_far"
        legs = [
            self._leg(n, "SELL" if sell_far else "BUY", 1.0, pn, quantity=q, segment="futures",
                      exchange="NFO", product="NRML"),
            self._leg(f, "BUY" if sell_far else "SELL", 1.0, pf, quantity=q, segment="futures",
                      exchange="NFO", product="NRML"),
        ]
        notional = q * (pn + pf)
        return TradeStructure(
            legs=legs, direction=signal["direction"], hedge_ratio=1.0,
            notional_per_unit=notional, capital_required=q * (pn + pf) * 0.10,
            margin_required=q * (pn + pf) * 0.10,  # calendar spreads get margin benefit
            expected_holding_days=float(signal["expected_holding_days"]),
        )

    def check_exit(self, point: SyncedPoint) -> tuple[bool, str]:
        if self.open is None:
            return False, ""
        if self._near_dte <= float(self.p["near_close_days"]):
            return True, "near_expiry_roll"
        if abs(self._z) <= float(self.p["exit_zscore"]):
            return True, "converged"
        if abs(self._z) >= float(self.p["stop_zscore"]):
            return True, "stop_zscore"
        max_days = int(self.p["max_holding_days"])
        if max_days and (self._i - self.open.entry_index) >= max_days:
            return True, "max_holding_days"
        return False, ""

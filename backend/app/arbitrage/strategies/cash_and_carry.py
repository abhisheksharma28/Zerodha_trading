"""Cash-and-Carry / Reverse Cash-and-Carry (2-leg, BASIS_ARBITRAGE).

The nearest thing to true arbitrage on this platform, but still NOT
risk-free: the annualised edge is the futures premium minus financing
minus dividends minus every cost, and it only crystallises if both legs
are executed together and carried to expiry (or the basis collapses
early). Margin on the short future is real capital.
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


class CashAndCarryStrategy(ArbitrageStrategy):
    N_LEGS: ClassVar[int] = 2

    SPEC: ClassVar[ArbSpec] = ArbSpec(
        slug="cash-and-carry",
        name="Cash-and-Carry / Reverse Cash-and-Carry",
        category=ArbCategory.BASIS_ARBITRAGE,
        description=(
            "Buy spot + sell the future when the future's annualised premium exceeds financing "
            "+ dividends + costs (cash-and-carry); mirror it when the future trades at a discount "
            "(reverse), if allow_reverse."
        ),
        logic=(
            "basis = future - spot; annualised_basis = basis/spot * 365/days_to_expiry. Enter "
            "cash-and-carry when net_annualised_carry (= annualised_basis - financing - dividend "
            "yield) exceeds min_carry_annual; enter reverse when it is below -min_carry_annual. "
            "Exit when the basis converges (|Z| <= exit_zscore), the carry disappears, or "
            "close_days_before_expiry is reached."
        ),
        legs="spot equity/index (cash leg, financed) + its near future",
        data_requirements=["aligned spot and near-future OHLCV", "the near contract expiry date",
                           "financing rate and dividend assumptions"],
        latency_sensitivity="medium",
        min_net_edge_bps_default=25.0,
        infra_note="needs verified F&O historical data for a multi-expiry backtest; margin on the "
        "short future is real capital",
        warning="The 'locked-in' edge assumes simultaneous fills and carry to expiry — slippage on "
        "one leg, an early margin call, or a special dividend can erase it.",
        supported_timeframes=("1d",),
    )

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        **BASIS_COMMON,
        "financing_rate_override": ParamSpec("number", 0.0,
                                             "Override the financing rate for the carry maths "
                                             "(0 = use financing_rate_annual).", min=0.0, max=1.0),
        "min_carry_annual": ParamSpec("number", 0.02,
                                      "Minimum net annualised carry to open (fraction).",
                                      min=0.0, max=1.0),
        "allow_reverse": ParamSpec("boolean", True, "Also take reverse cash-and-carry."),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(min_carry_annual=0.035, allow_reverse=False,
                               close_days_before_expiry=3, max_holding_days=45,
                               min_net_edge_bps=35.0, position_fraction=0.4),
        "balanced": preset(min_carry_annual=0.02, allow_reverse=True, close_days_before_expiry=2,
                           max_holding_days=45, min_net_edge_bps=25.0, position_fraction=0.5),
        "aggressive": preset(min_carry_annual=0.008, allow_reverse=True, close_days_before_expiry=1,
                             max_holding_days=45, min_net_edge_bps=12.0, position_fraction=0.6),
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        m = int(self.p["lookback"]) + 5
        self._basis: deque[float] = deque(maxlen=m)
        self._syms: list[str] = []
        self._spot = 0.0
        self._fut = 0.0
        self._z = 0.0
        self._dte = 30.0
        self._ann = 0.0

    def _fin_rate(self) -> float:
        ov = float(self.p["financing_rate_override"])
        return ov if ov > 0 else float(self.p["financing_rate_annual"])

    def _on_point(self, point: SyncedPoint) -> None:
        if not self._syms:
            self._syms = list(point.bars)
        spot_s, fut_s = self._syms
        self._spot = point.bars[spot_s].close
        self._fut = point.bars[fut_s].close
        if self._spot <= 0:
            return
        basis = self._fut - self._spot
        self._basis.append(basis)
        self._dte = max(0.5, days_to_expiry(point, float(self.p["expiry_ts"])))
        self._ann = basis / self._spot * 365.0 / self._dte
        lb = int(self.p["lookback"])
        if len(self._basis) >= lb:
            mu = rolling_mean(list(self._basis), lb) or 0.0
            sd = rolling_std(list(self._basis), lb) or 0.0
            self._z = (basis - mu) / sd if sd > 1e-9 else 0.0

    def _net_carry(self) -> float:
        return self._ann - self._fin_rate() - float(self.p["dividend_yield_annual"])

    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        if len(self._basis) < int(self.p["lookback"]) or len(self._syms) < 2:
            return None
        if self._dte <= float(self.p["close_days_before_expiry"]):
            return None
        nc = self._net_carry()
        thr = float(self.p["min_carry_annual"])
        if nc >= thr:
            direction = "cash_and_carry"
        elif self.p["allow_reverse"] and nc <= -thr:
            direction = "reverse_cash_and_carry"
        else:
            return None
        # edge captured at convergence ~ |basis| (minus carry already netted)
        edge_bps = abs(self._fut - self._spot) / self._spot * 1e4
        return {
            "direction": direction,
            "basis": round(self._fut - self._spot, 4),
            "annualised_basis": round(self._ann, 4),
            "net_annualised_carry": round(nc, 4),
            "days_to_expiry": round(self._dte, 1),
            "hedge_ratio": 1.0,
            "gross_edge_bps": round(edge_bps, 2),
            "expected_holding_days": round(min(self._dte, float(self.p["max_holding_days"]) or self._dte), 1),
        }

    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        spot_s, fut_s = self._syms
        ps, pf = self._spot, self._fut
        cap = float(self.p["capital"]) * float(self.p["position_fraction"])
        q = int(cap / (ps + pf))
        if q <= 0:
            return None
        carry = signal["direction"] == "cash_and_carry"
        legs = [
            self._leg(spot_s, "BUY" if carry else "SELL", 1.0, ps, quantity=q, segment="equity",
                      product="CNC", is_financing_leg=carry, borrow_required=not carry),
            self._leg(fut_s, "SELL" if carry else "BUY", 1.0, pf, quantity=q, segment="futures",
                      exchange="NFO", product="NRML"),
        ]
        notional = q * (ps + pf)
        return TradeStructure(
            legs=legs, direction=signal["direction"], hedge_ratio=1.0,
            notional_per_unit=notional, capital_required=q * ps + q * pf * 0.15,
            margin_required=q * pf * 0.15,
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
        # carry gone the wrong way
        nc = self._net_carry()
        if self.open.structure.direction == "cash_and_carry" and nc < 0:
            return True, "carry_lost"
        if self.open.structure.direction == "reverse_cash_and_carry" and nc > 0:
            return True, "carry_lost"
        max_days = int(self.p["max_holding_days"])
        if max_days and (self._i - self.open.entry_index) >= max_days:
            return True, "max_holding_days"
        return False, ""

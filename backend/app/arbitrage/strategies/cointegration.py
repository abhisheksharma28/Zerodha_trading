"""Cointegration Spread Trading (2-leg).

STATISTICAL_ARBITRAGE, stricter than plain pairs: an Engle-Granger / ADF
gate on the residual, a half-life sanity band, a rolling-stability check
that rejects a pair whose cointegration keeps failing, and a choice of
static-OLS / rolling-OLS / Kalman-filter hedge ratio.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, ClassVar

from app.arbitrage.base import ArbitrageStrategy, ArbSpec
from app.arbitrage.data_sync import SyncedPoint
from app.arbitrage.strategies.pairs import _half_life
from app.arbitrage.types import ArbCategory, TradeStructure
from app.strategies.indicators import adf_tstat, rolling_beta, rolling_mean, rolling_std
from app.strategies.library.base import ParamSpec, preset


def _static_ols(y: list[float], x: list[float]) -> float:
    n = len(y)
    if n < 5:
        return 1.0
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return 1.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / sxx


class _Kalman:
    """1-D Kalman filter on the hedge ratio beta in y = beta*x."""

    def __init__(self, q: float = 1e-5, r: float = 1e-3) -> None:
        self.beta = 1.0
        self.p = 1.0
        self.q = q
        self.r = r

    def update(self, y: float, x: float) -> float:
        self.p += self.q
        denom = x * self.p * x + self.r
        k = (self.p * x) / denom if denom else 0.0
        self.beta += k * (y - self.beta * x)
        self.p *= 1.0 - k * x
        return self.beta


class CointegrationSpreadStrategy(ArbitrageStrategy):
    N_LEGS: ClassVar[int] = 2

    SPEC: ClassVar[ArbSpec] = ArbSpec(
        slug="cointegration-arb",
        name="Cointegration Spread Trading",
        category=ArbCategory.STATISTICAL_ARBITRAGE,
        description=(
            "Trades the residual of a cointegrating regression between two instruments, with an "
            "ADF stationarity gate, a half-life band, and a rolling-stability check that rejects "
            "pairs whose cointegration keeps breaking."
        ),
        logic=(
            "Fit the hedge ratio (static OLS / rolling OLS / Kalman). residual = log(A) - "
            "beta*log(B). Require ADF(residual) <= adf_threshold AND ADF passing on >= "
            "stability_min_frac of rolling sub-windows AND half_life in [hl_min, hl_max]. Then "
            "trade the residual Z-score: enter |Z| >= entry_zscore, exit |Z| <= exit_zscore, stop "
            "|Z| >= stop_zscore, bail on any gate failure (model breakdown)."
        ),
        legs="2 equities, cointegration-weighted market-neutral",
        data_requirements=["daily or intraday OHLCV for both legs", "aligned timestamps",
                           "at least coint_lookback bars before the first trade"],
        latency_sensitivity="low",
        min_net_edge_bps_default=20.0,
        infra_note="retail-viable on daily bars; needs a stable cointegrating relationship",
        warning="Cointegration is a historical property that can and does vanish; the stability "
                "gate reduces but does not remove that risk.",
        supported_timeframes=("1d", "60m"),
    )

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "hedge_ratio_method": ParamSpec("enum", "rolling_ols", "How beta is estimated.",
                                        choices=("static_ols", "rolling_ols", "kalman")),
        "regression_window": ParamSpec("integer", 90, "Rolling-OLS window (rolling_ols only).",
                                       min=20, max=1000),
        "refit_period": ParamSpec("integer", 20, "Bars between static-OLS refits.", min=1, max=250),
        "lookback": ParamSpec("integer", 60, "Residual Z-score window.", min=10, max=1000),
        "coint_lookback": ParamSpec("integer", 250, "Bars for the ADF gate + stability check.",
                                    min=40, max=2000),
        "adf_threshold": ParamSpec("number", -3.0, "Max ADF t-stat for stationarity.",
                                   min=-10.0, max=0.0),
        "stability_min_frac": ParamSpec("number", 0.6,
                                        "Min fraction of rolling ADF sub-windows that must pass.",
                                        min=0.0, max=1.0, group="filter"),
        "hl_min": ParamSpec("number", 2.0, "Minimum acceptable half-life (bars).", min=0.5, max=200.0,
                            group="filter"),
        "hl_max": ParamSpec("number", 60.0, "Maximum acceptable half-life (bars).", min=2.0,
                            max=500.0, group="filter"),
        "entry_zscore": ParamSpec("number", 2.0, "Absolute residual Z to enter.", min=0.5, max=10.0),
        "exit_zscore": ParamSpec("number", 0.3, "Residual Z (toward 0) to exit.", min=0.0, max=10.0),
        "stop_zscore": ParamSpec("number", 3.5, "Residual Z beyond which to force-exit.",
                                 min=0.5, max=20.0, group="risk"),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(hedge_ratio_method="static_ols", refit_period=40, lookback=90,
                               adf_threshold=-3.4, stability_min_frac=0.75, hl_max=40.0,
                               entry_zscore=2.5, exit_zscore=0.5, stop_zscore=4.0,
                               max_holding_days=25, min_net_edge_bps=30.0),
        "balanced": preset(hedge_ratio_method="rolling_ols", regression_window=90, lookback=60,
                           adf_threshold=-3.0, stability_min_frac=0.6, entry_zscore=2.0,
                           exit_zscore=0.3, stop_zscore=3.5, max_holding_days=30,
                           min_net_edge_bps=20.0),
        "aggressive": preset(hedge_ratio_method="kalman", lookback=40, adf_threshold=-2.7,
                             stability_min_frac=0.45, hl_max=90.0, entry_zscore=1.5,
                             exit_zscore=0.0, stop_zscore=3.0, max_holding_days=20,
                             min_net_edge_bps=12.0),
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        m = max(int(self.p["coint_lookback"]), int(self.p["regression_window"]),
                int(self.p["lookback"])) + 5
        self._la: deque[float] = deque(maxlen=m)
        self._lb: deque[float] = deque(maxlen=m)
        self._resid: deque[float] = deque(maxlen=m)
        self._syms: list[str] = []
        self._beta = 1.0
        self._z = 0.0
        self._adf: float | None = None
        self._stab = 0.0
        self._hl = 10.0
        self._kf = _Kalman()
        self._last_fit = -10_000

    def _on_point(self, point: SyncedPoint) -> None:
        if not self._syms:
            self._syms = list(point.bars)
        a, b = self._syms
        pa, pb = point.bars[a].close, point.bars[b].close
        if pa <= 0 or pb <= 0:
            return
        self._la.append(math.log(pa))
        self._lb.append(math.log(pb))

        method = self.p["hedge_ratio_method"]
        if method == "kalman":
            self._beta = self._kf.update(self._la[-1], self._lb[-1])
        elif method == "rolling_ols":
            rw = int(self.p["regression_window"])
            if len(self._la) >= rw:
                bt = rolling_beta(list(self._la), list(self._lb), rw)
                if bt and abs(bt) < 20:
                    self._beta = bt
        else:  # static_ols, refit every refit_period bars
            if (self._i - self._last_fit) >= int(self.p["refit_period"]) and len(self._la) >= 20:
                self._beta = _static_ols(list(self._la), list(self._lb))
                self._last_fit = self._i

        self._resid.append(self._la[-1] - self._beta * self._lb[-1])
        lb = int(self.p["lookback"])
        if len(self._resid) >= lb:
            mu = rolling_mean(list(self._resid), lb) or 0.0
            sd = rolling_std(list(self._resid), lb) or 0.0
            self._z = (self._resid[-1] - mu) / sd if sd > 1e-9 else 0.0

        clb = int(self.p["coint_lookback"])
        if len(self._resid) >= clb:
            window = list(self._resid)[-clb:]
            self._adf = adf_tstat(window)
            self._hl = _half_life(window)
            # rolling stability: ADF on 5 overlapping thirds
            sub = max(30, clb // 3)
            passes = tot = 0
            for start in range(0, clb - sub + 1, max(1, sub // 2)):
                t = adf_tstat(window[start:start + sub])
                if t is not None:
                    tot += 1
                    passes += t <= float(self.p["adf_threshold"])
            self._stab = passes / tot if tot else 0.0

    def _gate_ok(self) -> tuple[bool, str]:
        if self._adf is None:
            return False, "warming_up"
        if self._adf > float(self.p["adf_threshold"]):
            return False, "adf_fail"
        if self._stab < float(self.p["stability_min_frac"]):
            return False, "unstable_cointegration"
        if not (float(self.p["hl_min"]) <= self._hl <= float(self.p["hl_max"])):
            return False, "half_life_out_of_band"
        return True, ""

    def discover_opportunity(self, point: SyncedPoint) -> dict[str, Any] | None:
        if len(self._resid) < int(self.p["lookback"]) or len(self._syms) < 2:
            return None
        ok, _ = self._gate_ok()
        if not ok or abs(self._z) < float(self.p["entry_zscore"]):
            return None
        sd = rolling_std(list(self._resid), int(self.p["lookback"])) or 0.0
        return {
            "direction": "short_spread" if self._z > 0 else "long_spread",
            "zscore": round(self._z, 3),
            "hedge_ratio": round(self._beta, 6),
            "adf_tstat": round(self._adf, 3) if self._adf is not None else None,
            "cointegration_stability": round(self._stab, 3),
            "half_life": round(self._hl, 1),
            "gross_edge_bps": round(abs(self._z) * sd * 1e4, 2),
            "expected_holding_days": round(min(self._hl, 60.0), 1),
        }

    def build_structure(self, signal: dict[str, Any], point: SyncedPoint) -> TradeStructure | None:
        a, b = self._syms
        pa, pb = point.bars[a].close, point.bars[b].close
        cap = float(self.p["capital"]) * float(self.p["position_fraction"])
        beta = abs(float(signal["hedge_ratio"])) or 1.0
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
        ok, why = self._gate_ok()
        if not ok:
            return True, f"model_breakdown:{why}"
        max_days = int(self.p["max_holding_days"])
        if max_days and (self._i - self.open.entry_index) >= max_days:
            return True, "max_holding_days"
        return False, ""

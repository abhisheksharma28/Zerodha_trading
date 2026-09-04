"""Evaluate a fixed-weight multi-asset portfolio over the discovery
price store: build its return series with periodic rebalancing +
transaction costs, then the full metric battery, an in-sample /
out-of-sample split, and a regime breakdown.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.discovery import normalize
from app.discovery.metrics import instrument_metrics
from app.regime import classify

_PPY = 12
_MARKET = "SPY"


def _portfolio_returns(
    dates: list[str], rets: dict[str, list[float]], target: dict[str, float],
    *, cost_bps: float,
) -> tuple[list[float], float]:
    syms = list(target)
    w0 = np.array([target[s] for s in syms], dtype=float)
    w0 = w0 / w0.sum()
    R = np.array([rets[s] for s in syms], dtype=float)  # N x T
    T = R.shape[1]

    w = w0.copy()
    out: list[float] = []
    turnover = 0.0
    cost = cost_bps / 10_000.0
    for t in range(T):
        rt = R[:, t]
        port_r = float(w @ rt)
        # rebalance back to target each period; charge cost on the traded amount
        drifted = w * (1.0 + rt)
        drifted = drifted / drifted.sum()
        trade = float(np.abs(w0 - drifted).sum())
        turnover += trade
        out.append(port_r - trade * cost)
        w = w0.copy()
    ann_turnover = (turnover / max(T, 1)) * _PPY
    return out, ann_turnover


def evaluate(
    db: Any, weights: dict[str, float], *, currency: str = "USD",
    cost_bps: float = 10.0, oos_frac: float = 0.35,
) -> dict[str, Any]:
    syms = [s for s, w in weights.items() if w and w > 0]
    if len(syms) < 2:
        return {"available": False, "reason": "need >= 2 instruments with weight"}
    need = [*syms, _MARKET] if _MARKET not in syms else syms
    fr = normalize.returns_frame(db, need, currency=currency)
    rets = fr["returns"]
    missing = [s for s in syms if s not in rets]
    if missing:
        return {"available": False, "reason": f"no common history for {missing}"}

    tgt = {s: weights[s] for s in syms}
    tot = sum(tgt.values())
    tgt = {s: v / tot for s, v in tgt.items()}

    dates = fr["return_dates"]
    port, ann_turnover = _portfolio_returns(dates, rets, tgt, cost_bps=cost_bps)
    mkt = rets.get(_MARKET)
    m = instrument_metrics(port, market_returns=mkt)

    # per-asset return contribution (weight * asset total return)
    contrib = {
        s: round(tgt[s] * (float(np.prod(1.0 + np.array(rets[s]))) - 1.0) * 100.0, 2)
        for s in syms
    }
    eff_n = round(1.0 / sum(v * v for v in tgt.values()), 2)

    # IS / OOS split
    cut = int(len(port) * (1.0 - oos_frac))
    is_m = instrument_metrics(port[:cut]) if cut >= 6 else {}
    oos_m = instrument_metrics(port[cut:]) if len(port) - cut >= 6 else {}

    # regime breakdown — classify each period from the market series up to it
    by_regime: dict[str, list[float]] = {}
    if mkt is not None:
        prices = [1.0]
        for r in mkt:
            prices.append(prices[-1] * (1.0 + r))
        for i, r in enumerate(port):
            st = classify(prices[: i + 2])  # causal
            by_regime.setdefault(st.regime, []).append(r)
    regime_stats = {
        rg: {
            "n": len(rs),
            "return_pct": round((float(np.prod(1.0 + np.array(rs))) - 1.0) * 100.0, 2),
            "ann_vol_pct": round(float(np.std(rs, ddof=1)) * (12 ** 0.5) * 100.0, 2) if len(rs) > 2 else None,
        }
        for rg, rs in by_regime.items()
    }

    return {
        "available": True,
        "currency": fr["currency"],
        "period_start": fr["dates"][0] if fr["dates"] else None,
        "period_end": fr["dates"][-1] if fr["dates"] else None,
        "weights": {s: round(v, 4) for s, v in tgt.items()},
        "metrics": {**m, "annual_turnover_pct": round(ann_turnover * 100.0, 1),
                    "effective_n": eff_n},
        "contribution_pct": contrib,
        "in_sample": is_m,
        "out_of_sample": oos_m,
        "by_regime": regime_stats,
        "cost_bps": cost_bps,
    }

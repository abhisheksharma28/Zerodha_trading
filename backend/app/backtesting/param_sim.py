"""Parameter-perturbation simulator.

Runs a strategy many times with every numeric parameter independently
jittered within +/- ``pct`` percent of the supplied value, and reports the
distribution of the resulting KPIs (return, CAGR, Sharpe, Sortino, max
drawdown, Calmar, win rate, profit factor, trade count).

The question it answers: *is this exact parameter set a fragile knife-edge,
or does performance hold across its immediate neighbourhood?* A tight
distribution centred on the base result = robust; a wide one, or a base
result that sits in the tail, = fragile / likely curve-fit.

Deterministic given ``seed``. Pure over pre-fetched candles + an engine —
no DB, no network.
"""

from __future__ import annotations

import math
import random
from typing import Any

from app.backtesting.costs import CostModel
from app.backtesting.engine import BacktestEngine, BacktestRunResult
from app.backtesting.performance import compute_performance
from app.backtesting.trades import reconstruct_trades

_KPIS = (
    "return_pct", "cagr_pct", "sharpe_ratio", "sortino_ratio",
    "max_drawdown_pct", "calmar_ratio", "win_rate_pct", "profit_factor", "total_trades",
)
_SKIP_PARAMS = {"capital_allocation"}


def _pct(sv: list[float], q: float) -> float:
    if not sv:
        return 0.0
    if len(sv) == 1:
        return sv[0]
    pos = q * (len(sv) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sv) - 1)
    return sv[lo] + (sv[hi] - sv[lo]) * (pos - lo)


def _summary(vals: list[float]) -> dict[str, float]:
    sv = sorted(v for v in vals if v is not None and not math.isnan(v) and not math.isinf(v))
    if not sv:
        return {"min": 0, "p5": 0, "p25": 0, "p50": 0, "p75": 0, "p95": 0, "max": 0,
                "mean": 0, "std": 0}
    mean = sum(sv) / len(sv)
    var = sum((v - mean) ** 2 for v in sv) / len(sv)
    return {
        "min": round(sv[0], 4), "p5": round(_pct(sv, 0.05), 4), "p25": round(_pct(sv, 0.25), 4),
        "p50": round(_pct(sv, 0.50), 4), "p75": round(_pct(sv, 0.75), 4),
        "p95": round(_pct(sv, 0.95), 4), "max": round(sv[-1], 4),
        "mean": round(mean, 4), "std": round(math.sqrt(var), 4),
    }


def _kpis(result: BacktestRunResult, candles: dict[str, list], capital: float,
          periods_per_year: int) -> tuple[dict[str, float], bool]:
    mark = {s: float(b[-1].close) for s, b in candles.items() if b}
    trades = reconstruct_trades(
        result.fills, fill_costs=[f.cost for f in result.fills], mark_prices=mark
    )
    m = compute_performance(result.equity_curve, trades, initial_capital=capital,
                            total_costs=result.total_costs, trading_days_per_year=periods_per_year)
    pf = m.get("profit_factor")
    return (
        {
            "return_pct": float(m.get("return_pct") or 0.0),
            "cagr_pct": float(m.get("cagr_pct") or 0.0),
            "sharpe_ratio": float(m.get("sharpe_ratio") or 0.0),
            "sortino_ratio": float(m.get("sortino_ratio") or 0.0),
            "max_drawdown_pct": float(m.get("max_drawdown_pct") or 0.0),
            "calmar_ratio": float(m.get("calmar_ratio") or 0.0),
            "win_rate_pct": float(m.get("win_rate_pct") or 0.0),
            "profit_factor": float(pf) if pf is not None and math.isfinite(pf) else 0.0,
            "total_trades": float(m.get("total_trades") or 0),
        },
        bool(result.diagnostics.ruined),
    )


def _perturb(base: dict[str, Any], schema: dict[str, Any], rng: random.Random,
             frac: float) -> tuple[dict[str, Any], list[str]]:
    out = dict(base)
    touched: list[str] = []
    for name, spec in schema.items():
        if name in _SKIP_PARAMS or spec.type not in ("integer", "number"):
            continue
        cur = base.get(name, spec.default)
        try:
            cur = float(cur)
        except (TypeError, ValueError):
            continue
        jittered = cur * (1.0 + rng.uniform(-frac, frac))
        if spec.min is not None:
            jittered = max(spec.min, jittered)
        if spec.max is not None:
            jittered = min(spec.max, jittered)
        if spec.type == "integer":
            jittered = int(round(jittered))
            if spec.min is not None:
                jittered = max(int(spec.min), jittered)
        out[name] = jittered
        touched.append(name)
    return out, touched


def run_param_sim(
    strategy_cls: type,
    base_params: dict[str, Any],
    candles_by_instrument: dict[str, list],
    *,
    initial_capital: float,
    cost_model: CostModel | None = None,
    max_gross_exposure: float = 4.0,
    pct: float = 5.0,
    n_samples: int = 30,
    seed: int = 0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    schema = strategy_cls.all_params() if hasattr(strategy_cls, "all_params") else {}
    resolve = getattr(strategy_cls, "resolve_params", lambda p: p)
    frac = max(0.0, pct) / 100.0

    def _run(params: dict[str, Any]) -> tuple[dict[str, float], bool]:
        eng = BacktestEngine(strategy_cls, params, initial_capital, cost_model=cost_model,
                             max_gross_exposure=max_gross_exposure)
        return _kpis(eng.run(candles_by_instrument), candles_by_instrument, initial_capital,
                     periods_per_year)

    base_kpis, base_ruined = _run(resolve(dict(base_params)))

    rng = random.Random(seed)
    rows: list[dict[str, float]] = []
    ruined = 0
    perturbed_names: list[str] = []
    for _ in range(max(1, n_samples)):
        p, touched = _perturb(base_params, schema, rng, frac)
        perturbed_names = touched
        try:
            k, r = _run(resolve(p))
        except Exception:  # noqa: BLE001 - a bad draw shouldn't sink the sim
            continue
        rows.append(k)
        ruined += r

    dist = {kpi: _summary([row[kpi] for row in rows]) for kpi in _KPIS} if rows else {}
    ruined_frac = round((ruined + base_ruined) / (len(rows) + 1), 4)

    notes: list[str] = []
    fragile = False
    if ruined_frac > 0:
        fragile = True
        notes.append(f"{ruined_frac:.0%} of the +/-{pct:g}% neighbourhood ruins the book.")
    if dist:
        sh = dist["sharpe_ratio"]
        if sh["std"] > 0.5 and sh["std"] >= abs(base_kpis["sharpe_ratio"]) + 1e-9:
            fragile = True
            notes.append(
                f"Sharpe swings +/-{sh['std']:.2f} across the neighbourhood "
                f"(base {base_kpis['sharpe_ratio']:.2f}) — knife-edge."
            )
        rr = dist["return_pct"]
        if not (rr["p5"] <= base_kpis["return_pct"] <= rr["p95"]):
            fragile = True
            notes.append("Base return sits outside the 5–95% band of its own neighbourhood.")
        if abs(base_kpis["return_pct"]) > 1 and (rr["p95"] - rr["p5"]) > 4 * abs(base_kpis["return_pct"]):
            fragile = True
            notes.append("Return spread across +/-5% params exceeds 4x the base return.")
    if not notes:
        notes.append(f"Performance holds across the +/-{pct:g}% parameter neighbourhood.")

    return {
        "pct": pct,
        "n_samples": len(rows),
        "seed": seed,
        "perturbed_params": sorted(perturbed_names),
        "base": {k: round(v, 4) for k, v in base_kpis.items()},
        "base_ruined": base_ruined,
        "ruined_fraction": ruined_frac,
        "distribution": dist,
        "verdict": "fragile" if fragile else "stable",
        "notes": notes,
    }

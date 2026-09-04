"""Adversarial validation for a discovered portfolio — try to break it.

  deflated_sharpe   multiple-testing-adjusted Sharpe (PSR + DSR)
  block_bootstrap   autocorrelation-preserving resample of the return path
  weight_perturbation   fragility to +/- weight jitter
  start_date_sensitivity   dependence on one lucky start
  rejection_rules   the Part 22 checklist
  stability_score   0-100 "is this believable" score + label

``validate_portfolio`` runs them all and folds the result into a single
verdict. The engine ranks survivors of this pass, not raw backtest looks.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np

from app.discovery import portfolio
from app.discovery.fitness import score as fitness_score

_N = NormalDist()
_PPY = 12


# --- multiple-testing-adjusted Sharpe --------------------------------

def deflated_sharpe(returns: list[float], *, n_trials: int) -> dict[str, Any]:
    """Probabilistic + Deflated Sharpe (López de Prado, 2014). All on the
    per-period Sharpe (not annualised)."""
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 12:
        return {"available": False, "reason": "series too short"}
    sd = r.std(ddof=1)
    sr = float(r.mean() / sd) if sd > 1e-12 else 0.0
    # skew / kurtosis of the returns
    z = (r - r.mean()) / (sd + 1e-12)
    skew = float((z**3).mean())
    kurt = float((z**4).mean())  # non-excess

    # PSR against SR* = 0
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2))
    psr = float(_N.cdf(sr * math.sqrt(n - 1) / denom))

    # expected max Sharpe from N independent trials of pure noise
    trials = max(int(n_trials), 2)
    e_max = (1.0 - np.euler_gamma) * _N.inv_cdf(1.0 - 1.0 / trials) + \
        np.euler_gamma * _N.inv_cdf(1.0 - 1.0 / (trials * math.e))
    sr_star = e_max / math.sqrt(n - 1)
    dsr = float(_N.cdf((sr - sr_star) * math.sqrt(n - 1) / denom))

    return {
        "available": True,
        "sharpe_period": round(sr, 4),
        "sharpe_annual": round(sr * math.sqrt(_PPY), 3),
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "n_trials": trials,
        "psr": round(psr, 4),               # P(true SR > 0)
        "deflated_sharpe": round(dsr, 4),   # P(true SR > the trials-adjusted bar)
        "sr_star": round(sr_star, 4),
    }


# --- bootstrap ------------------------------------------------------

def _path_stats(r: np.ndarray) -> tuple[float, float, float]:
    curve = np.cumprod(1.0 + r)
    years = r.size / _PPY
    cagr = curve[-1] ** (1.0 / years) - 1.0 if curve[-1] > 0 else -1.0
    dd = float((curve / np.maximum.accumulate(curve) - 1.0).min())
    sd = r.std(ddof=1)
    sharpe = (r.mean() / sd) * math.sqrt(_PPY) if sd > 1e-12 else 0.0
    return float(cagr), dd, float(sharpe)


def block_bootstrap(
    returns: list[float], *, block: int = 6, sims: int = 4000, seed: int = 17,
) -> dict[str, Any]:
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < block * 3:
        return {"available": False, "reason": "series too short for the block size"}
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    starts_max = n - block
    cagr, dd, sharpe = [], [], []
    for _ in range(sims):
        starts = rng.integers(0, starts_max + 1, size=n_blocks)
        path = np.concatenate([r[s : s + block] for s in starts])[:n]
        c, d, s = _path_stats(path)
        cagr.append(c)
        dd.append(d)
        sharpe.append(s)

    def pct(a: list[float], q: float) -> float:
        return round(float(np.percentile(a, q)), 4)

    return {
        "available": True,
        "sims": sims,
        "block": block,
        "cagr_pct": {p: pct(cagr, p) * 100 for p in (5, 25, 50, 75, 95)},
        "max_drawdown_pct": {p: pct(dd, p) * 100 for p in (5, 25, 50, 75, 95)},
        "sharpe": {p: pct(sharpe, p) for p in (5, 25, 50, 75, 95)},
        "prob_negative_cagr": round(float(np.mean(np.array(cagr) < 0)), 4),
        "prob_dd_worse_than_25pct": round(float(np.mean(np.array(dd) < -0.25)), 4),
    }


# --- perturbation + start-date -----------------------------------

def weight_perturbation(
    db: Any, weights: dict[str, float], *, jitter: float = 0.05, n: int = 40,
    currency: str = "USD", seed: int = 23,
) -> dict[str, Any]:
    base = portfolio.evaluate(db, weights, currency=currency)
    if not base.get("available"):
        return {"available": False, "reason": base.get("reason")}
    base_fit = fitness_score(base)["alpha_score"]
    rng = np.random.default_rng(seed)
    syms = list(weights)
    w0 = np.array([weights[s] for s in syms])
    fits = []
    for _ in range(n):
        w = np.clip(w0 * (1.0 + rng.uniform(-jitter, jitter, size=len(syms))), 1e-4, None)
        w = w / w.sum()
        ev = portfolio.evaluate(db, dict(zip(syms, w, strict=True)), currency=currency)
        if ev.get("available"):
            fits.append(fitness_score(ev)["alpha_score"])
    if not fits:
        return {"available": False, "reason": "no perturbed portfolio evaluated"}
    arr = np.array(fits)
    drop = base_fit - float(arr.min())
    return {
        "available": True,
        "base_alpha_score": round(base_fit, 2),
        "perturbed_mean": round(float(arr.mean()), 2),
        "perturbed_std": round(float(arr.std()), 2),
        "worst": round(float(arr.min()), 2),
        "max_drop": round(drop, 2),
        "fragile": bool(drop > 15.0),   # a +/-5% wiggle should not cost >15 pts
    }


def start_date_sensitivity(
    db: Any, weights: dict[str, float], *, step: int = 3, currency: str = "USD",
) -> dict[str, Any]:
    from app.discovery import normalize

    syms = list(weights)
    fr = normalize.returns_frame(db, syms, currency=currency)
    rets = fr["returns"]
    usable = [s for s in syms if s in rets]
    if len(usable) < 2:
        return {"available": False, "reason": "insufficient history"}
    w = np.array([weights[s] for s in usable])
    w = w / w.sum()
    R = np.array([rets[s] for s in usable])  # N x T
    port = (w @ R)
    T = port.size
    sharpes, cagrs = [], []
    for start in range(0, max(1, T - 36), step):
        seg = port[start:]
        if seg.size < 24:
            break
        c, _d, s = _path_stats(seg)
        cagrs.append(c)
        sharpes.append(s)
    if not sharpes:
        return {"available": False, "reason": "not enough windows"}
    return {
        "available": True,
        "windows": len(sharpes),
        "sharpe_median": round(float(np.median(sharpes)), 3),
        "sharpe_worst": round(float(np.min(sharpes)), 3),
        "sharpe_best": round(float(np.max(sharpes)), 3),
        "cagr_median_pct": round(float(np.median(cagrs)) * 100, 2),
        "cagr_worst_pct": round(float(np.min(cagrs)) * 100, 2),
    }


# --- rejection rules + stability -------------------------------

def rejection_rules(ev: dict[str, Any], val: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    m = ev.get("metrics", {})
    contrib = ev.get("contribution_pct", {})
    tot = sum(v for v in contrib.values() if v > 0) or 1.0
    if contrib and max(contrib.values()) / tot > 0.55:
        fails.append("one asset drives > 55% of the return")
    if max(ev.get("weights", {}).values() or [0]) > 0.45:
        fails.append("single-name weight > 45%")

    isr = (ev.get("in_sample") or {}).get("sharpe")
    oos = (ev.get("out_of_sample") or {}).get("sharpe")
    if isr and isr > 0.3 and oos is not None and oos < 0.3 * isr:
        fails.append("out-of-sample Sharpe collapses vs in-sample")

    by_reg = ev.get("by_regime", {})
    rets = {k: v.get("return_pct") for k, v in by_reg.items() if v.get("return_pct") is not None}
    pos = {k: v for k, v in rets.items() if v > 0}
    if len(rets) >= 3 and len(pos) == 1 and sum(rets.values()) > 0:
        fails.append("gains come from a single market regime")

    if (m.get("annual_turnover_pct") or 0) > 250:
        fails.append("annual turnover > 250%")

    ds = val.get("deflated_sharpe", {})
    if ds.get("available") and ds.get("deflated_sharpe", 1.0) < 0.90:
        fails.append(f"deflated Sharpe {ds['deflated_sharpe']:.2f} < 0.90 (likely data-mined)")
    if ds.get("available") and ds.get("psr", 1.0) < 0.95:
        fails.append(f"probabilistic Sharpe {ds['psr']:.2f} < 0.95 (not significant)")

    if val.get("perturbation", {}).get("fragile"):
        fails.append("small weight changes destroy the fitness (fragile)")

    bb = val.get("block_bootstrap", {})
    if bb.get("available") and bb.get("prob_negative_cagr", 0) > 0.25:
        fails.append("bootstrap: > 25% chance of a negative CAGR")
    return fails


def stability_score(ev: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    def band(x, lo, hi):
        if x is None:
            return 0.5
        t = (x - lo) / (hi - lo) if hi != lo else 0.5
        return max(0.0, min(1.0, t))

    m = ev.get("metrics", {})
    isr = (ev.get("in_sample") or {}).get("sharpe")
    oos = (ev.get("out_of_sample") or {}).get("sharpe")
    bb = val.get("block_bootstrap", {})
    pt = val.get("perturbation", {})
    ds = val.get("deflated_sharpe", {})
    regs = ev.get("by_regime", {})
    reg_pos = sum(1 for v in regs.values() if (v.get("return_pct") or 0) > 0)

    parts = {
        "historical": 0.20 * band(m.get("sharpe"), 0.2, 1.4),
        "out_of_sample": 0.20 * (band(oos / isr, 0.4, 1.1) if (isr and isr > 0.1 and oos is not None) else 0.5),
        "regime": 0.15 * band(reg_pos / max(len(regs), 1), 0.4, 1.0),
        "parameter_robustness": 0.15 * (1.0 - band(pt.get("max_drop"), 0.0, 25.0) if pt.get("available") else 0.5),
        "diversification": 0.10 * band(m.get("effective_n"), 2.0, 7.0),
        "drawdown_stability": 0.10 * band(bb.get("prob_dd_worse_than_25pct"), 0.5, 0.02) if bb.get("available") else 0.05,
        "cost_resilience": 0.05 * band(m.get("annual_turnover_pct"), 200.0, 20.0),
        "simplicity": 0.05 * band(m.get("effective_n"), 2.0, 6.0),
    }
    if ds.get("available"):
        parts["out_of_sample"] = 0.5 * parts["out_of_sample"] + 0.5 * (0.20 * band(ds.get("deflated_sharpe"), 0.5, 0.99))
    sc = round(100.0 * sum(parts.values()), 1)
    label = (
        "Exceptional robustness" if sc >= 90 else
        "Strong" if sc >= 80 else
        "Acceptable" if sc >= 70 else
        "Fragile" if sc >= 60 else
        "High overfitting risk"
    )
    return {"stability_score": sc, "label": label,
            "components": {k: round(v * 100, 1) for k, v in parts.items()}}


def validate_portfolio(
    db: Any, weights: dict[str, float], *, n_trials: int = 1,
    currency: str = "USD", cost_bps: float = 10.0, bootstrap_sims: int = 4000,
) -> dict[str, Any]:
    ev = portfolio.evaluate(db, weights, currency=currency, cost_bps=cost_bps)
    if not ev.get("available"):
        return {"available": False, "reason": ev.get("reason")}

    from app.discovery import normalize

    fr = normalize.returns_frame(db, list(weights), currency=currency)
    usable = [s for s in weights if s in fr["returns"]]
    w = np.array([weights[s] for s in usable])
    w = w / w.sum()
    port_rets = list(np.array([fr["returns"][s] for s in usable]).T @ w)

    val: dict[str, Any] = {
        "deflated_sharpe": deflated_sharpe(port_rets, n_trials=n_trials),
        "block_bootstrap": block_bootstrap(port_rets, sims=bootstrap_sims),
        "perturbation": weight_perturbation(db, {s: weights[s] for s in usable}, currency=currency),
        "start_date_sensitivity": start_date_sensitivity(db, {s: weights[s] for s in usable}, currency=currency),
    }
    val["rejections"] = rejection_rules(ev, val)
    val.update(stability_score(ev, val))
    val["alpha_score"] = fitness_score(ev)["alpha_score"]
    val["verdict"] = (
        "reject" if (val["rejections"] and val["stability_score"] < 60)
        else "downgrade" if val["rejections"]
        else "pass"
    )
    return {"available": True, "evaluation": ev, "validation": val}

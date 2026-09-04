"""Portfolio optimizer library for the Alpha Discovery Engine.

Every optimizer takes a periodic return matrix and returns
``{symbol: weight}`` (weights sum to 1, honour the constraint-mode box
bounds). The engine compares several — no single objective is trusted.

Methods: equal_weight, min_variance, max_sharpe, risk_parity,
max_diversification, min_correlation, hrp (Hierarchical Risk Parity).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.optimize import minimize

_PPY = 12  # monthly data

# constraint modes -> (min weight, max weight)
CONSTRAINT_MODES: dict[str, tuple[float, float]] = {
    "conservative": (0.0, 0.20),
    "balanced": (0.0, 0.30),
    "aggressive": (0.0, 0.40),
    "unrestricted": (0.0, 1.0),
}

METHODS = (
    "equal_weight", "min_variance", "max_sharpe", "risk_parity",
    "max_diversification", "min_correlation", "hrp",
)


def _moments(returns: dict[str, list[float]], syms: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    R = np.array([returns[s] for s in syms], dtype=float)  # N x T
    mu = R.mean(axis=1) * _PPY
    cov = np.cov(R) * _PPY
    if cov.ndim == 0:
        cov = cov.reshape(1, 1)
    vol = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = np.corrcoef(R) if R.shape[0] > 1 else np.array([[1.0]])
    return mu, np.nan_to_num(cov), vol, np.nan_to_num(corr, nan=0.0)


def _solve(objective, n: int, bounds: tuple[float, float]) -> np.ndarray:
    lo, hi = bounds
    hi = max(hi, 1.0 / n + 1e-6)  # a feasible box must allow an equal-weight point
    x0 = np.full(n, 1.0 / n)
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    res = minimize(
        objective, x0, method="SLSQP", bounds=[(lo, hi)] * n, constraints=cons,
        options={"maxiter": 500, "ftol": 1e-10},
    )
    w = np.clip(res.x, 0.0, None)
    return w / w.sum() if w.sum() > 0 else x0


def _w(syms: list[str], w: np.ndarray) -> dict[str, float]:
    return {s: round(float(x), 6) for s, x in zip(syms, w, strict=True)}


# --- optimizers --------------------------------------------------------

def equal_weight(syms: list[str], **_: Any) -> dict[str, float]:
    return {s: round(1.0 / len(syms), 6) for s in syms}


def min_variance(syms, returns, *, bounds=(0.0, 0.30), **_):
    _mu, cov, _vol, _corr = _moments(returns, syms)
    return _w(syms, _solve(lambda w: w @ cov @ w, len(syms), bounds))


def max_sharpe(syms, returns, *, bounds=(0.0, 0.30), **_):
    mu, cov, _vol, _corr = _moments(returns, syms)

    def neg_sharpe(w):
        vol = np.sqrt(max(w @ cov @ w, 1e-12))
        return -(w @ mu) / vol

    return _w(syms, _solve(neg_sharpe, len(syms), bounds))


def risk_parity(syms, returns, *, bounds=(0.0, 0.40), **_):
    """Equal risk contribution via the convex log-barrier formulation
    (Spinu): minimise 0.5 wᵀΣw − (1/n)Σ log wᵢ over wᵢ > 0, then normalise
    — scale-invariant, so no sum-to-one constraint is needed and it
    converges reliably. The upper box bound is enforced by a final
    water-fill."""
    _mu, cov, _vol, _corr = _moments(returns, syms)
    n = len(syms)

    def obj(w):
        return 0.5 * float(w @ cov @ w) - (1.0 / n) * float(np.sum(np.log(w)))

    x0 = np.full(n, 1.0 / n)
    res = minimize(
        obj, x0, method="SLSQP", bounds=[(1e-6, None)] * n,
        options={"maxiter": 500, "ftol": 1e-12},
    )
    w = np.clip(res.x, 1e-9, None)
    w = w / w.sum()
    _lo, hi = bounds
    if hi < 1.0:
        w = _waterfill(w, hi)
    return _w(syms, w)


def _waterfill(w: np.ndarray, cap: float) -> np.ndarray:
    out = w.copy()
    for _ in range(20):
        over = out > cap + 1e-9
        if not over.any():
            break
        excess = float((out[over] - cap).sum())
        out[over] = cap
        room = out < cap - 1e-9
        rtot = float(out[room].sum())
        if rtot <= 0:
            break
        out[room] += excess * (out[room] / rtot)
    return out / out.sum()


def max_diversification(syms, returns, *, bounds=(0.0, 0.30), **_):
    _mu, cov, vol, _corr = _moments(returns, syms)

    def neg_dr(w):
        port_vol = np.sqrt(max(w @ cov @ w, 1e-12))
        return -(w @ vol) / port_vol

    return _w(syms, _solve(neg_dr, len(syms), bounds))


def min_correlation(syms, returns, *, bounds=(0.0, 0.30), **_):
    _mu, _cov, _vol, corr = _moments(returns, syms)
    return _w(syms, _solve(lambda w: w @ corr @ w, len(syms), bounds))


def hrp(syms, returns, **_):
    """López de Prado Hierarchical Risk Parity: cluster by correlation
    distance, quasi-diagonalise, allocate by recursive inverse-variance
    bisection. Naturally moderate — ignores the box bounds."""
    _mu, cov, _vol, corr = _moments(returns, syms)
    n = len(syms)
    if n < 3:
        return equal_weight(syms)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, None))
    z = linkage(dist[np.triu_indices(n, 1)], method="average")
    order = _leaves(to_tree(z))

    w = np.ones(n)
    clusters = [order]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) <= 1:
                continue
            half = len(c) // 2
            left, right = c[:half], c[half:]
            vl = _cluster_var(cov, left)
            vr = _cluster_var(cov, right)
            alpha = 1.0 - vl / (vl + vr)
            for i in left:
                w[i] *= alpha
            for i in right:
                w[i] *= 1.0 - alpha
            nxt += [left, right]
        clusters = nxt
    w = w / w.sum()
    return {syms[i]: round(float(w[i]), 6) for i in range(n)}


def _leaves(node) -> list[int]:
    if node.is_leaf():
        return [node.id]
    return _leaves(node.get_left()) + _leaves(node.get_right())


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    ivp = 1.0 / np.clip(np.diag(sub), 1e-12, None)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)


_DISPATCH = {
    "equal_weight": equal_weight,
    "min_variance": min_variance,
    "max_sharpe": max_sharpe,
    "risk_parity": risk_parity,
    "max_diversification": max_diversification,
    "min_correlation": min_correlation,
    "hrp": hrp,
}


def optimize(
    method: str, syms: list[str], returns: dict[str, list[float]],
    *, constraint_mode: str = "balanced",
) -> dict[str, float]:
    if method not in _DISPATCH:
        raise ValueError(f"unknown method {method!r} (use {METHODS})")
    bounds = CONSTRAINT_MODES.get(constraint_mode, CONSTRAINT_MODES["balanced"])
    return _DISPATCH[method](syms, returns, bounds=bounds)

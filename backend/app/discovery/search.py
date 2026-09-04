"""Portfolio search — Monte Carlo + a genetic algorithm over the candidate
universe, ranked by the fitness score, with a Pareto frontier.

Deterministic given a seed. Every search records how many portfolios it
tested so a headline result can be deflated later (Part 18).
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.discovery import fitness, normalize, portfolio

logger = get_logger(__name__)

_MAX_EVAL_CACHE = 4000


def _prep(db: Session, symbols: list[str], currency: str) -> tuple[list[str], dict[str, list[float]]]:
    fr = normalize.returns_frame(db, symbols, currency=currency)
    usable = [s for s in symbols if s in fr["returns"] and len(fr["returns"][s]) >= 24]
    return usable, {s: fr["returns"][s] for s in usable}


def _evaluate(db: Session, weights: dict[str, float], currency: str, cost_bps: float,
              cache: dict[frozenset, dict]) -> dict[str, Any] | None:
    key = frozenset((s, round(w, 3)) for s, w in weights.items() if w > 1e-4)
    if key in cache:
        return cache[key]
    ev = portfolio.evaluate(db, weights, currency=currency, cost_bps=cost_bps)
    if not ev.get("available"):
        return None
    ev["fitness"] = fitness.score(ev)
    if len(cache) < _MAX_EVAL_CACHE:
        cache[key] = ev
    return ev


def _random_portfolio(rng, syms: list[str], n_lo: int, n_hi: int, wmax: float) -> dict[str, float]:
    n = int(rng.integers(n_lo, n_hi + 1))
    picks = list(rng.choice(syms, size=min(n, len(syms)), replace=False))
    for _ in range(20):
        w = rng.dirichlet(np.ones(len(picks)))
        if w.max() <= wmax + 1e-9:
            break
    w = np.minimum(w, wmax)
    w = w / w.sum()
    return dict(zip(picks, (round(float(x), 6) for x in w), strict=True))


def monte_carlo_search(
    db: Session, symbols: list[str], *, n_assets=(5, 10), n_portfolios: int = 2000,
    wmax: float = 0.35, currency: str = "USD", cost_bps: float = 10.0, seed: int = 7,
) -> dict[str, Any]:
    t0 = time.time()
    syms, _rets = _prep(db, symbols, currency)
    if len(syms) < n_assets[0]:
        return {"available": False, "reason": f"only {len(syms)} usable instruments"}
    rng = np.random.default_rng(seed)
    cache: dict[frozenset, dict] = {}
    evals: list[dict[str, Any]] = []
    tested = 0
    for _ in range(n_portfolios):
        wts = _random_portfolio(rng, syms, n_assets[0], min(n_assets[1], len(syms)), wmax)
        tested += 1
        ev = _evaluate(db, wts, currency, cost_bps, cache)
        if ev:
            evals.append(ev)
    return _finalise(evals, tested, "monte_carlo", seed, time.time() - t0)


def genetic_search(
    db: Session, symbols: list[str], *, n_assets=(5, 10), generations: int = 25,
    population: int = 40, wmax: float = 0.35, currency: str = "USD",
    cost_bps: float = 10.0, seed: int = 7,
) -> dict[str, Any]:
    t0 = time.time()
    syms, _rets = _prep(db, symbols, currency)
    if len(syms) < n_assets[0]:
        return {"available": False, "reason": f"only {len(syms)} usable instruments"}
    rng = np.random.default_rng(seed)
    cache: dict[frozenset, dict] = {}
    tested = 0

    def fit(wts):
        nonlocal tested
        tested += 1
        ev = _evaluate(db, wts, currency, cost_bps, cache)
        return (ev["fitness"]["alpha_score"] if ev else -1.0), ev

    pop = [_random_portfolio(rng, syms, n_assets[0], min(n_assets[1], len(syms)), wmax)
           for _ in range(population)]
    scored = [(f, ev, w) for w in pop for f, ev in [fit(w)]]
    best_evals: dict[frozenset, dict] = {}

    for _g in range(generations):
        scored.sort(key=lambda t: t[0], reverse=True)
        for _f, ev, w in scored[:10]:
            if ev:
                best_evals[frozenset(w.items())] = ev
        elite = [w for _f, _e, w in scored[: max(4, population // 5)]]
        children: list[dict[str, float]] = list(elite)
        while len(children) < population:
            a, b = rng.choice(len(elite), size=2, replace=len(elite) < 2)
            child = _crossover(rng, elite[int(a)], elite[int(b)], wmax)
            if rng.random() < 0.5:
                child = _mutate(rng, child, syms, n_assets, wmax)
            children.append(child)
        scored = [(f, ev, w) for w in children for f, ev in [fit(w)]]

    scored.sort(key=lambda t: t[0], reverse=True)
    for _f, ev, w in scored[:10]:
        if ev:
            best_evals[frozenset(w.items())] = ev
    return _finalise(list(best_evals.values()), tested, "genetic", seed, time.time() - t0)


def _crossover(rng, a: dict[str, float], b: dict[str, float], wmax: float) -> dict[str, float]:
    names = list(dict.fromkeys([*a, *b]))
    rng.shuffle(names)
    keep = names[: max(5, min(10, (len(a) + len(b)) // 2))]
    w = np.array([0.5 * a.get(s, 0.0) + 0.5 * b.get(s, 0.0) for s in keep])
    if w.sum() <= 0:
        w = np.ones(len(keep))
    w = np.minimum(w / w.sum(), wmax)
    w = w / w.sum()
    return dict(zip(keep, (round(float(x), 6) for x in w), strict=True))


def _mutate(rng, p: dict[str, float], syms: list[str], n_assets, wmax: float) -> dict[str, float]:
    names = list(p)
    if rng.random() < 0.5 and len(names) < min(n_assets[1], len(syms)):
        cand = [s for s in syms if s not in p]
        if cand:
            names.append(str(rng.choice(cand)))
    elif len(names) > n_assets[0]:
        names.pop(int(rng.integers(len(names))))
    w = np.array([p.get(s, 1.0 / len(names)) for s in names])
    w = np.abs(w + rng.normal(0.0, 0.05, size=len(names)))
    w = np.minimum(w / w.sum(), wmax)
    w = w / w.sum()
    return dict(zip(names, (round(float(x), 6) for x in w), strict=True))


def _finalise(evals, tested, method, seed, secs) -> dict[str, Any]:
    if not evals:
        return {"available": False, "reason": "no valid portfolio found",
                "tested": tested}
    # de-dupe on the weight set
    uniq: dict[frozenset, dict] = {}
    for e in evals:
        uniq.setdefault(frozenset(e["weights"].items()), e)
    evals = list(uniq.values())
    evals.sort(key=lambda e: e["fitness"]["alpha_score"], reverse=True)
    front = set(fitness.pareto_frontier(evals))
    top = evals[:10]
    logger.info("discovery_search", method=method, tested=tested,
                kept=len(evals), secs=round(secs, 1))
    return {
        "available": True,
        "method": method,
        "seed": seed,
        "tested": tested,
        "kept": len(evals),
        "elapsed_s": round(secs, 1),
        "top": [
            {
                "rank": i + 1,
                "weights": e["weights"],
                "alpha_score": e["fitness"]["alpha_score"],
                "on_pareto_frontier": i in front,  # front indexes the sorted list
                "metrics": e["metrics"],
                "category_scores": e["fitness"]["category_scores"],
                "out_of_sample": e.get("out_of_sample", {}),
                "by_regime": e.get("by_regime", {}),
            }
            for i, e in enumerate(top)
        ],
        "pareto_frontier": [
            {"weights": evals[i]["weights"], "alpha_score": evals[i]["fitness"]["alpha_score"],
             "cagr_pct": evals[i]["metrics"].get("cagr_pct"),
             "sharpe": evals[i]["metrics"].get("sharpe"),
             "max_drawdown_pct": evals[i]["metrics"].get("max_drawdown_pct")}
            for i in sorted(front)
        ],
    }

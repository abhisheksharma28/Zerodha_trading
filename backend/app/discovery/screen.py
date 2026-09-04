"""Instrument screening + correlation clustering for the discovery engine.

- ``screen()``  — per-instrument metric battery + a configurable composite
  ``screen_score`` (percentile-ranked and blended across the universe).
- ``cluster()`` — agglomerative clustering on return correlation, so the
  universe reduces to one representative per distinct risk/return trade
  ("don't pick 10 names that are the same trade"). Reused by the basket
  engine's correlation control.
- ``candidates()`` — the best-scored instrument(s) per cluster.

numpy only (agglomerative clustering is hand-rolled; no scipy).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.discovery import normalize
from app.discovery.metrics import instrument_metrics

# composite screen_score category weights (Part 5 of the spec). Configurable.
DEFAULT_WEIGHTS: dict[str, float] = {
    "return_quality": 0.20,     # cagr, rolling-return mean
    "risk_efficiency": 0.20,    # sharpe, sortino, calmar
    "drawdown_quality": 0.15,   # max_dd, ulcer, avg_dd  (less bad = higher)
    "consistency": 0.15,        # positive_period_pct, low rolling-return std
    "diversification": 0.15,    # low corr_to_market
    "robustness": 0.15,         # low rolling_sharpe_std, high rolling-return min
}

_MARKET = "SPY"  # proxy for corr-to-market


def _pct_rank(values: dict[str, float], *, higher_is_better: bool = True) -> dict[str, float]:
    """Map values to a 0..1 percentile rank across the set."""
    items = [(k, v) for k, v in values.items() if v is not None and np.isfinite(v)]
    if not items:
        return {}
    items.sort(key=lambda kv: kv[1], reverse=not higher_is_better)
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {k: i / (n - 1) for i, (k, _v) in enumerate(items)}


def _blend(ranks: dict[str, dict[str, float]], syms: list[str], weights: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in syms:
        num = 0.0
        wtot = 0.0
        for cat, w in weights.items():
            r = ranks.get(cat, {}).get(s)
            if r is None:
                continue
            num += w * r
            wtot += w
        out[s] = 100.0 * (num / wtot) if wtot > 0 else 0.0
    return out


def screen(
    db: Session,
    *,
    symbols: list[str] | None = None,
    currency: str = "USD",
    weights: dict[str, float] | None = None,
    market: str = _MARKET,
) -> dict[str, Any]:
    from app.discovery.service import _ingested_symbols

    weights = weights or DEFAULT_WEIGHTS
    syms = symbols or _ingested_symbols(db)
    if market not in syms:
        syms = [*syms, market]
    fr = normalize.returns_frame(db, syms, currency=currency)
    rets = fr["returns"]
    mkt = rets.get(market)

    per: dict[str, dict[str, Any]] = {}
    for s in syms:
        if s not in rets:
            continue
        # the market proxy is a real instrument too — score it, just skip its
        # self-correlation
        per[s] = instrument_metrics(rets[s], market_returns=mkt if s != market else None)

    usable = [s for s, m in per.items() if not m.get("insufficient")]

    # category -> {metric: (accessor, higher_is_better)}
    cats: dict[str, list[tuple[str, bool]]] = {
        "return_quality": [("cagr_pct", True), ("rolling_return_mean_pct", True)],
        "risk_efficiency": [("sharpe", True), ("sortino", True), ("calmar", True)],
        "drawdown_quality": [("max_drawdown_pct", True), ("ulcer_index", False),
                             ("avg_drawdown_pct", True)],
        "consistency": [("positive_period_pct", True), ("rolling_return_std_pct", False)],
        "diversification": [("corr_to_market", False)],
        "robustness": [("rolling_sharpe_std", False), ("rolling_return_min_pct", True)],
    }
    cat_ranks: dict[str, dict[str, float]] = {}
    for cat, metric_list in cats.items():
        sub: list[dict[str, float]] = []
        for metric, hib in metric_list:
            vals = {s: per[s].get(metric) for s in usable}
            sub.append(_pct_rank({k: v for k, v in vals.items() if v is not None}, higher_is_better=hib))
        # average the sub-metric ranks within the category
        cat_ranks[cat] = {
            s: float(np.mean([d[s] for d in sub if s in d])) if any(s in d for d in sub) else 0.5
            for s in usable
        }

    scores = _blend(cat_ranks, usable, weights)
    clusters = cluster({s: rets[s] for s in usable}, k=max(3, min(8, len(usable) // 2)))

    rows = [
        {
            "symbol": s,
            "screen_score": round(scores.get(s, 0.0), 2),
            "cluster": clusters.get(s),
            "metrics": per[s],
            "category_ranks": {c: round(cat_ranks[c].get(s, 0.0) * 100, 1) for c in cats},
        }
        for s in usable
    ]
    rows.sort(key=lambda r: r["screen_score"], reverse=True)
    return {
        "currency": fr["currency"],
        "n": len(rows),
        "period_start": fr["dates"][0] if fr["dates"] else None,
        "period_end": fr["dates"][-1] if fr["dates"] else None,
        "weights": weights,
        "instruments": rows,
        "excluded": [s for s in syms if s not in usable and s in per],
    }


def correlation_matrix(returns_by_sym: dict[str, list[float]]) -> tuple[list[str], np.ndarray]:
    syms = sorted(returns_by_sym)
    m = np.array([returns_by_sym[s] for s in syms], dtype=float)
    if m.shape[0] < 2 or m.shape[1] < 3:
        return syms, np.eye(len(syms))
    c = np.corrcoef(m)
    return syms, np.nan_to_num(c, nan=0.0)


def cluster(returns_by_sym: dict[str, list[float]], *, k: int) -> dict[str, int]:
    """Agglomerative (average-linkage) clustering on ``1 - corr`` distance
    (0 = same trade, 2 = the opposite trade — anti-correlated assets are a
    *different* cluster, not the same one), merging until ``k`` remain."""
    syms, corr = correlation_matrix(returns_by_sym)
    n = len(syms)
    if n <= k or n < 2:
        return {s: i for i, s in enumerate(syms)}

    dist = 1.0 - corr
    members: list[list[int]] = [[i] for i in range(n)]
    while len(members) > k:
        best = (1e9, 0, 1)
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                d = float(np.mean([dist[i, j] for i in members[a] for j in members[b]]))
                if d < best[0]:
                    best = (d, a, b)
        _d, a, b = best
        members[a].extend(members[b])
        members.pop(b)

    out: dict[str, int] = {}
    for cid, group in enumerate(members):
        for idx in group:
            out[syms[idx]] = cid
    return out


def candidates(
    db: Session, *, k: int = 12, per_cluster: int = 1, currency: str = "USD",
) -> dict[str, Any]:
    """A low-correlation candidate set for the portfolio search: cluster the
    screened universe, take the top-``per_cluster`` by screen_score from
    each cluster, return up to ``k`` ranked by score."""
    sc = screen(db, currency=currency)
    score_of = {r["symbol"]: r["screen_score"] for r in sc["instruments"]}
    by_cluster: dict[int, list[dict[str, Any]]] = {}
    for row in sc["instruments"]:
        by_cluster.setdefault(row["cluster"], []).append(row)

    picks: list[str] = []
    for rows in by_cluster.values():
        rows.sort(key=lambda x: x["screen_score"], reverse=True)
        picks.extend(r["symbol"] for r in rows[:per_cluster])
    picks.sort(key=lambda s: score_of[s], reverse=True)
    return {
        "n_clusters": len(by_cluster),
        "candidates": picks[: max(k, 5)],
        "clusters": {
            str(cid): [r["symbol"] for r in rows] for cid, rows in sorted(by_cluster.items())
        },
    }

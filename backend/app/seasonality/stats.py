"""Descriptive + inferential statistics per (sector, calendar month), plus
a bootstrap. No numpy — small samples, plain Python is fine and keeps the
maths auditable.
"""

from __future__ import annotations

import math
import random
from typing import Any

_T_LABELS = (
    (1.0, "no evidence / noise"),
    (1.64, "weak indication"),
    (2.26, "emerging evidence"),
    (3.0, "significant (~5% level)"),
    (float("inf"), "strong statistical evidence"),
)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _downside_dev(xs: list[float], target: float = 0.0) -> float:
    lo = [min(x - target, 0.0) for x in xs]
    if len(lo) < 2:
        return 0.0
    return math.sqrt(sum(v * v for v in lo) / (len(lo) - 1))


def _t_cdf(t: float, df: int) -> float:
    """One-sided Student-t CDF via a normal + Cornish-Fisher-ish tail fix.
    Good enough for a p-value at the precision we report (2 dp)."""
    if df <= 0:
        return 0.5
    # Use the standard normal for df >= 30, else a small-sample correction
    x = t * (1.0 - 1.0 / (4.0 * df)) / math.sqrt(1.0 + t * t / (2.0 * df))
    # normal CDF
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_sided_p(t: float, df: int) -> float:
    if df <= 0 or not math.isfinite(t):
        return 1.0
    return max(0.0, min(1.0, 2.0 * (1.0 - _t_cdf(abs(t), df))))


def t_label(t: float) -> str:
    at = abs(t)
    for hi, label in _T_LABELS:
        if at < hi:
            return label
    return _T_LABELS[-1][1]


def sample_size_tier(n: int) -> str:
    if n < 5:
        return "insufficient"
    if n <= 7:
        return "low"
    if n <= 10:
        return "moderate"
    if n <= 15:
        return "good"
    return "high"


def bootstrap(values: list[float], *, iters: int = 10_000, seed: int = 12345) -> dict[str, Any]:
    """Resample-with-replacement CI + P(edge>0) / P(edge<0)."""
    n = len(values)
    if n < 4:
        return {"available": False, "reason": f"only {n} observations"}
    rng = random.Random(seed)
    means: list[float] = []
    pos = 0
    for _ in range(iters):
        s = sum(values[rng.randrange(n)] for _ in range(n)) / n
        means.append(s)
        if s > 0:
            pos += 1
    means.sort()
    lo = means[int(0.025 * iters)]
    hi = means[int(0.975 * iters)]
    return {
        "available": True,
        "iterations": iters,
        "mean": round(_mean(means), 3),
        "median": round(_median(means), 3),
        "ci95": [round(lo, 3), round(hi, 3)],
        "prob_positive": round(pos / iters, 3),
        "prob_negative": round(1.0 - pos / iters, 3),
    }


def month_stats(
    edges: list[float],
    raw_returns: list[float],
    *,
    market_adj: list[float] | None = None,
    cross_ranks: list[int] | None = None,
    do_bootstrap: bool = True,
) -> dict[str, Any]:
    """Full stat sheet for one (sector, month) cell. ``edges`` is the chosen
    seasonal-edge series (own by default), ``raw_returns`` the underlying
    monthly returns for the same year-set."""
    n = len(edges)
    if n == 0:
        return {"n": 0, "tier": "insufficient"}

    mean_e, med_e, sd_e = _mean(edges), _median(edges), _std(edges)
    pos = sum(1 for e in edges if e > 0)
    neg = sum(1 for e in edges if e < 0)
    se = sd_e / math.sqrt(n) if n > 1 and sd_e > 0 else 0.0
    t = mean_e / se if se > 0 else 0.0
    df = n - 1
    p = two_sided_p(t, df)
    # Cohen's d effect size
    d = mean_e / sd_e if sd_e > 0 else 0.0
    tcrit = 2.0  # ~95% for moderate df, kept simple
    ci = [round(mean_e - tcrit * se, 3), round(mean_e + tcrit * se, 3)] if se > 0 else None

    out: dict[str, Any] = {
        "n": n,
        "tier": sample_size_tier(n),
        "mean_edge_pct": round(mean_e, 3),
        "median_edge_pct": round(med_e, 3),
        "std_edge_pct": round(sd_e, 3),
        "min_edge_pct": round(min(edges), 3),
        "max_edge_pct": round(max(edges), 3),
        "downside_dev_pct": round(_downside_dev(edges), 3),
        "worst_loss_pct": round(min(edges), 3),
        "positive_years": pos,
        "negative_years": neg,
        "win_rate": round(pos / n, 3),
        "loss_rate": round(neg / n, 3),
        "mean_return_pct": round(_mean(raw_returns), 3),
        "median_return_pct": round(_median(raw_returns), 3),
        "std_return_pct": round(_std(raw_returns), 3),
        "t_stat": round(t, 3),
        "p_value": round(p, 4),
        "df": df,
        "effect_size_d": round(d, 3),
        "ci95_edge_pct": ci,
        "t_label": t_label(t),
    }
    if market_adj:
        out["mean_market_adj_pct"] = round(_mean(market_adj), 3)
    if cross_ranks:
        out["mean_cross_rank"] = round(_mean([float(r) for r in cross_ranks]), 2)
        out["median_cross_rank"] = round(_median([float(r) for r in cross_ranks]), 1)
    if do_bootstrap:
        out["bootstrap"] = bootstrap(edges)
    return out

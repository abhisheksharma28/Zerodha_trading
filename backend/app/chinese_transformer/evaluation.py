"""Alpha evaluation — is the ranking actually predictive out-of-sample?

All metrics are computed per rebalance date on the *test* rows only, then
aggregated. The headline number is Rank-IC (cross-sectional Spearman
correlation between predicted score and realized forward return) and its
information ratio ICIR = mean(IC) / std(IC).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return 0.0
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt((ra**2).sum() * (rb**2).sum())
    return float((ra * rb).sum() / denom) if denom > 0 else 0.0


def evaluate(
    scored: pd.DataFrame,
    *,
    score_col: str = "score",
    fwd_col: str = "fwd_return",
    quantiles: int = 5,
    top_k: int = 10,
) -> dict[str, Any]:
    """``scored`` is indexed by (date, symbol) and has ``score_col`` +
    ``fwd_col``. Returns aggregate + per-date IC series + quantile spread."""
    if scored.empty:
        return {"rank_ic_mean": 0.0, "icir": 0.0, "n_dates": 0, "note": "no test rows"}

    per_date: list[dict[str, Any]] = []
    q_returns = np.zeros(quantiles)
    q_counts = np.zeros(quantiles)
    topk_hits = 0.0
    topk_dates = 0
    for d, grp in scored.groupby(level=0):
        s = grp[score_col].to_numpy(dtype=float)
        f = grp[fwd_col].to_numpy(dtype=float)
        if len(s) < max(quantiles, 5):
            continue
        ic = _spearman(s, f)
        qid = np.clip((np.argsort(np.argsort(s)) / max(len(s) - 1, 1) * quantiles).astype(int),
                      0, quantiles - 1)
        for q in range(quantiles):
            m = qid == q
            if m.any():
                q_returns[q] += f[m].mean()
                q_counts[q] += 1
        order = np.argsort(s)[::-1][:top_k]
        topk_hits += float((f[order] > np.median(f)).mean())
        topk_dates += 1
        per_date.append({"date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                         "rank_ic": round(ic, 4),
                         "top_minus_bottom": round(float(
                             f[qid == quantiles - 1].mean() - f[qid == 0].mean()), 5)})

    ics = np.array([r["rank_ic"] for r in per_date])
    q_avg = (q_returns / np.where(q_counts == 0, 1, q_counts)).tolist()
    return {
        "n_dates": len(per_date),
        "rank_ic_mean": round(float(ics.mean()), 4) if ics.size else 0.0,
        "rank_ic_std": round(float(ics.std()), 4) if ics.size else 0.0,
        "rank_ic_hit_rate": round(float((ics > 0).mean()), 3) if ics.size else 0.0,
        "icir": round(float(ics.mean() / ics.std()), 3) if ics.size and ics.std() > 0 else 0.0,
        "quantile_fwd_return": [round(x, 5) for x in q_avg],
        "long_short_spread": round(float(q_avg[-1] - q_avg[0]), 5) if len(q_avg) >= 2 else 0.0,
        "top_k": top_k,
        "precision_at_k": round(topk_hits / topk_dates, 3) if topk_dates else 0.0,
        "per_date": per_date,
    }

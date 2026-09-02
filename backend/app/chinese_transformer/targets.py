"""Cross-sectional target construction.

The label at rebalance date ``t`` is built only from bars in the window
``(t, t + horizon]`` — strictly future relative to the features, and the
model is trained to rank, not to predict a price.

Three configurable targets:

* ``rank``           — percentile of forward return across the universe
                       on that date (0 = worst, 1 = best).
* ``bucket``         — quantile bucket id (default quintiles), for a
                       classification head / CrossEntropy.
* ``risk_adjusted``  — forward return divided by realized forward
                       volatility, then percentile-ranked cross-sectionally.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


def _fwd_return(closes: np.ndarray, dates: np.ndarray, t: date, horizon: int) -> float | None:
    idx = np.searchsorted(dates, np.datetime64(t), side="right") - 1
    if idx < 0 or idx + horizon >= len(closes):
        return None
    p0, p1 = closes[idx], closes[idx + horizon]
    if p0 <= 0 or p1 <= 0:
        return None
    return float(p1 / p0 - 1.0)


def _fwd_vol(closes: np.ndarray, dates: np.ndarray, t: date, horizon: int) -> float | None:
    idx = np.searchsorted(dates, np.datetime64(t), side="right") - 1
    if idx < 0 or idx + horizon >= len(closes):
        return None
    seg = closes[idx : idx + horizon + 1]
    if (seg <= 0).any() or len(seg) < 3:
        return None
    r = np.diff(seg) / seg[:-1]
    return float(np.std(r)) or None


def build_targets(
    bars_by_symbol: dict[str, list[Any]],
    *,
    rebalance_dates: list[date],
    horizon: int = 20,
    kind: str = "rank",
    n_buckets: int = 5,
) -> pd.DataFrame:
    """Return a frame indexed by (date, symbol) with columns:
    ``fwd_return``, ``target`` (the learning label) and ``fwd_return_rank``.
    Rows without a full forward window are dropped.
    """
    idx: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for sym, bars in bars_by_symbol.items():
        ds = np.array([np.datetime64(_d(b)) for b in bars])
        cs = np.array([float(b.close) for b in bars])
        idx[sym] = (ds, cs)

    records: list[dict[str, Any]] = []
    for t in rebalance_dates:
        fr: dict[str, float] = {}
        fv: dict[str, float] = {}
        for sym, (ds, cs) in idx.items():
            r = _fwd_return(cs, ds, t, horizon)
            if r is None:
                continue
            fr[sym] = r
            if kind == "risk_adjusted":
                v = _fwd_vol(cs, ds, t, horizon)
                fv[sym] = r / v if v and v > 0 else 0.0
        if len(fr) < max(n_buckets, 5):
            continue
        syms = list(fr)
        base = np.array([fv[s] for s in syms]) if kind == "risk_adjusted" else np.array(
            [fr[s] for s in syms])
        ranks = _pct_rank(base)
        ret_ranks = _pct_rank(np.array([fr[s] for s in syms]))
        buckets = np.clip((ranks * n_buckets).astype(int), 0, n_buckets - 1)
        for i, s in enumerate(syms):
            label = (
                float(buckets[i]) if kind == "bucket"
                else float(ranks[i])
            )
            records.append({
                "date": pd.Timestamp(t), "symbol": s,
                "fwd_return": fr[s], "fwd_return_rank": float(ret_ranks[i]),
                "target": label,
            })
    if not records:
        return pd.DataFrame(
            columns=["date", "symbol", "fwd_return", "fwd_return_rank", "target"]
        ).set_index(["date", "symbol"])
    return pd.DataFrame.from_records(records).set_index(["date", "symbol"]).sort_index()


def _pct_rank(x: np.ndarray) -> np.ndarray:
    if len(x) <= 1:
        return np.zeros_like(x, dtype=float)
    return np.argsort(np.argsort(x)) / (len(x) - 1)


def _d(b: Any) -> date:
    from app.chinese_transformer.data_quality import _ts_to_date

    return _ts_to_date(getattr(b, "timestamp", None)) or date.min

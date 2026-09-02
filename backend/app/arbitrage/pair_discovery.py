"""Pair discovery: scan a universe for tradeable statistical-arbitrage pairs.

For each candidate pair it computes return correlation, an Engle-Granger
ADF t-stat on the OLS residual, the residual half-life, a rough liquidity
score, and a spread-stability score (rolling ADF pass rate). Ranks by a
blended score; a pair is only "tradeable" when it is cointegrated, has a
sane half-life and enough liquidity.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from app.strategies.base import Bar
from app.strategies.indicators import adf_tstat, rolling_correlation


def _log_closes(bars: list[Bar]) -> list[float]:
    return [math.log(b.close) for b in bars if b.close and b.close > 0]


def _ols_beta(y: list[float], x: list[float]) -> float:
    n = min(len(y), len(x))
    if n < 10:
        return 1.0
    y, x = y[-n:], x[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / sxx if sxx else 1.0


def _half_life(resid: list[float]) -> float:
    if len(resid) < 20:
        return 999.0
    lag = resid[:-1]
    delta = [resid[i] - resid[i - 1] for i in range(1, len(resid))]
    n = len(delta)
    mx = sum(lag) / n
    my = sum(delta) / n
    sxx = sum((v - mx) ** 2 for v in lag)
    if sxx <= 0:
        return 999.0
    b = sum((lag[i] - mx) * (delta[i] - my) for i in range(n)) / sxx
    if b >= 0 or (1 + b) <= 0:
        return 999.0
    return -math.log(2) / math.log(1 + b)


def _stability(resid: list[float], adf_threshold: float) -> float:
    n = len(resid)
    if n < 90:
        return 0.0
    sub = max(30, n // 3)
    passes = tot = 0
    for start in range(0, n - sub + 1, max(1, sub // 2)):
        t = adf_tstat(resid[start:start + sub])
        if t is not None:
            tot += 1
            passes += t <= adf_threshold
    return passes / tot if tot else 0.0


def discover_pairs(
    candles_by_symbol: dict[str, list[Bar]],
    *,
    min_bars: int = 250,
    min_abs_correlation: float = 0.6,
    adf_threshold: float = -3.0,
    hl_min: float = 2.0,
    hl_max: float = 60.0,
    top_n: int = 40,
    same_sector: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    logs: dict[str, list[float]] = {}
    liq: dict[str, float] = {}
    for s, bars in candles_by_symbol.items():
        lc = _log_closes(bars)
        if len(lc) >= min_bars:
            logs[s] = lc
            liq[s] = sum((b.close or 0) * (b.volume or 0) for b in bars[-20:]) / 20.0

    rows: list[dict[str, Any]] = []
    for a, b in combinations(sorted(logs), 2):
        la, lb = logs[a], logs[b]
        n = min(len(la), len(lb))
        la, lb = la[-n:], lb[-n:]
        ra = [la[i] - la[i - 1] for i in range(1, n)]
        rb = [lb[i] - lb[i - 1] for i in range(1, n)]
        corr = rolling_correlation(ra, rb, min(len(ra), 250)) or 0.0
        if abs(corr) < min_abs_correlation:
            continue
        beta = _ols_beta(la, lb)
        if not (0.05 < abs(beta) < 20):
            continue
        resid = [la[i] - beta * lb[i] for i in range(n)]
        adf = adf_tstat(resid[-min(n, 500):])
        hl = _half_life(resid[-min(n, 500):])
        stab = _stability(resid[-min(n, 500):], adf_threshold)
        min_liq = min(liq.get(a, 0.0), liq.get(b, 0.0))
        liq_score = max(0.0, min(100.0, 20.0 * math.log10(max(min_liq, 1.0)) - 100.0))
        cointegrated = adf is not None and adf <= adf_threshold
        tradeable = bool(cointegrated and hl_min <= hl <= hl_max and liq_score >= 20.0
                         and stab >= 0.5)
        sector_rel = None
        if same_sector:
            sector_rel = same_sector.get(a) == same_sector.get(b) and same_sector.get(a)
        score = (
            35.0 * (min(1.0, -(adf or 0.0) / 4.0) if cointegrated else 0.0)
            + 20.0 * stab
            + 15.0 * (1.0 - min(1.0, abs(hl - 10.0) / 50.0) if hl < 900 else 0.0)
            + 15.0 * abs(corr)
            + 15.0 * (liq_score / 100.0)
        )
        rows.append({
            "symbol_a": a, "symbol_b": b, "hedge_ratio": round(beta, 6),
            "return_correlation": round(corr, 4),
            "adf_tstat": round(adf, 3) if adf is not None else None,
            "cointegrated": cointegrated,
            "half_life_bars": round(hl, 1) if hl < 900 else None,
            "spread_stability": round(stab, 3),
            "liquidity_score": round(liq_score, 1),
            "same_sector": sector_rel,
            "tradeable": tradeable,
            "discovery_score": round(score, 1),
            "bars_used": n,
        })
    rows.sort(key=lambda r: r["discovery_score"], reverse=True)
    return rows[:top_n]

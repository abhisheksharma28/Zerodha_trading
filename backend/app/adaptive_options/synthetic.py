"""Synthetic option-chain builder for the adaptive backtest.

Given a real underlying spot for a date and an IV anchor, generate a
plausible ``ChainSnapshot``: a skewed vol surface (put skew + a mild
smile), Black-Scholes prices, and Gaussian-shaped OI (heavier puts below
spot, calls above) so the PCR / positioning / greeks engines have
something real-shaped to read.

This is NOT a faithful reproduction of the market's chain. Every result
built on it is flagged ``synthetic_data: true`` and must never be treated
as evidence a strategy works — it exercises the *mechanics* of the adaptive
decision process only.
"""

from __future__ import annotations

import math
from datetime import datetime

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainRow, ChainSnapshot
from app.options.greeks import bs_price

_STEP = {"NIFTY": 50.0, "BANKNIFTY": 100.0, "FINNIFTY": 50.0, "MIDCPNIFTY": 25.0}


def build_chain(
    underlying: str,
    spot: float,
    as_of: datetime,
    dte: float,
    *,
    base_iv: float,
    skew: float = 0.6,
    smile: float = 2.5,
    n_each_side: int = 20,
    prev: ChainSnapshot | None = None,
    seed: int = 0,
) -> ChainSnapshot:
    step = _STEP.get(underlying.upper(), 50.0)
    atm = round(spot / step) * step
    t = max(dte, 0.5) / 365.0
    rng = _lcg(seed ^ int(spot))
    prev_by_k = {r.strike: r for r in prev.rows} if prev else {}

    rows: list[ChainRow] = []
    for i in range(-n_each_side, n_each_side + 1):
        k = atm + i * step
        if k <= 0:
            continue
        m = (k - spot) / spot                      # moneyness
        iv = max(0.04, base_iv * (1.0 - skew * m + smile * m * m))
        c_px = bs_price(spot, k, t, iv, is_call=True)
        p_px = bs_price(spot, k, t, iv, is_call=False)
        # OI: log-normal-ish humps a little OTM on each side
        c_oi = 55_000 * math.exp(-((k - (spot + 1.2 * step * 3)) ** 2) / (2 * (step * 8) ** 2)) + 3_000
        p_oi = 60_000 * math.exp(-((k - (spot - 1.2 * step * 3)) ** 2) / (2 * (step * 8) ** 2)) + 3_000
        c_oi *= 0.85 + 0.3 * next(rng)
        p_oi *= 0.85 + 0.3 * next(rng)
        pr = prev_by_k.get(k)
        rows.append(ChainRow(
            strike=k, call_oi=round(c_oi), put_oi=round(p_oi),
            call_chg_oi=round(c_oi - (pr.call_oi if pr else c_oi)),
            put_chg_oi=round(p_oi - (pr.put_oi if pr else p_oi)),
            call_volume=round(c_oi * (0.2 + 0.3 * next(rng))),
            put_volume=round(p_oi * (0.2 + 0.3 * next(rng))),
            call_ltp=round(max(0.05, c_px), 2), put_ltp=round(max(0.05, p_px), 2),
            call_iv=round(iv, 4), put_iv=round(iv, 4),
        ))
    return ChainSnapshot(underlying.upper(), _expiry_iso(as_of, dte), spot, as_of, float(dte), rows)


def anchor_iv(realized_vol: float | None, iv_rank_hint: float | None = None) -> float:
    """A stand-in for ATM IV when there is no real chain: realized vol with a
    small variance-risk-premium uplift, clamped to a sane band."""
    rv = realized_vol if (realized_vol and realized_vol > 0) else 0.13
    iv = rv * 1.15
    if iv_rank_hint is not None:
        iv *= 0.85 + 0.004 * max(0.0, min(100.0, iv_rank_hint))
    return max(0.06, min(0.55, iv))


def _expiry_iso(as_of: datetime, dte: float) -> str:
    from datetime import timedelta
    return (as_of.date() + timedelta(days=int(round(dte)))).isoformat()


def _lcg(seed: int):
    x = (seed & 0x7FFFFFFF) or 12345
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


def cfg_base_iv(cfg: AdaptiveConfig, realized_vol: float | None) -> float:
    return anchor_iv(realized_vol)

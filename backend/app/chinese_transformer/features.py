"""Multi-factor feature engineering.

Two stages:

1. ``raw_features`` — per-symbol features from *causal* OHLCV arrays (the
   last element is the decision bar; nothing after it is visible). Covers
   price/momentum, volatility, volume/liquidity and technical structure.
2. ``cross_section`` — turns raw features into cross-sectional signals:
   the z-score and percentile rank of each raw feature *across the
   universe on that date*, plus proxied market and sector context. This is
   what makes the model reason about "good relative to every other stock",
   not "good in absolute terms".

Every column is declared in ``FEATURE_SPECS`` with its category, lookback
and normalization, so the feature dashboard and leakage tests can reason
about them. No fundamental features here: the only fundamentals available
on this platform are current snapshots, not point-in-time, so using them
in a historical panel would leak. They are added live-only, elsewhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.strategies.indicators import (
    adx,
    atr,
    bollinger,
    ema,
    rsi,
    sma,
)


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    category: str          # price_momentum | volatility | volume_liquidity | technical
                           # | cross_sectional | market | sector
    lookback: int
    normalization: str     # raw | ratio | zscore_xs | pct_rank_xs | pct

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "lookback": self.lookback,
            "normalization": self.normalization,
        }


# raw per-symbol features and the horizons they use
_RAW: list[FeatureSpec] = [
    FeatureSpec("ret_1", "price_momentum", 1, "pct"),
    FeatureSpec("ret_5", "price_momentum", 5, "pct"),
    FeatureSpec("ret_10", "price_momentum", 10, "pct"),
    FeatureSpec("ret_20", "price_momentum", 20, "pct"),
    FeatureSpec("ret_60", "price_momentum", 60, "pct"),
    FeatureSpec("ret_120", "price_momentum", 120, "pct"),
    FeatureSpec("mom_accel", "price_momentum", 60, "raw"),
    FeatureSpec("dist_sma20", "price_momentum", 20, "ratio"),
    FeatureSpec("dist_sma50", "price_momentum", 50, "ratio"),
    FeatureSpec("dist_sma100", "price_momentum", 100, "ratio"),
    FeatureSpec("dist_sma200", "price_momentum", 200, "ratio"),
    FeatureSpec("sma20_slope", "price_momentum", 20, "ratio"),
    FeatureSpec("ema_spread", "price_momentum", 26, "ratio"),
    FeatureSpec("dist_52w_high", "price_momentum", 252, "ratio"),
    FeatureSpec("trend_persistence", "price_momentum", 60, "raw"),
    FeatureSpec("vol_20", "volatility", 20, "raw"),
    FeatureSpec("vol_60", "volatility", 60, "raw"),
    FeatureSpec("atr_pct_14", "volatility", 14, "ratio"),
    FeatureSpec("parkinson_20", "volatility", 20, "raw"),
    FeatureSpec("downside_dev_20", "volatility", 20, "raw"),
    FeatureSpec("max_dd_120", "volatility", 120, "ratio"),
    FeatureSpec("rel_volume_20", "volume_liquidity", 20, "ratio"),
    FeatureSpec("volume_z_60", "volume_liquidity", 60, "raw"),
    FeatureSpec("amihud_20", "volume_liquidity", 20, "raw"),
    FeatureSpec("turnover_accel", "volume_liquidity", 60, "ratio"),
    FeatureSpec("rsi_14", "technical", 14, "raw"),
    FeatureSpec("macd_hist_norm", "technical", 26, "ratio"),
    FeatureSpec("adx_14", "technical", 14, "raw"),
    FeatureSpec("bb_pos_20", "technical", 20, "raw"),
    FeatureSpec("stoch_k_14", "technical", 14, "raw"),
]

# raw features that also get cross-sectional z-score + percentile-rank columns
_XS_SOURCE = [
    "ret_20", "ret_60", "ret_120", "mom_accel", "dist_sma50", "dist_52w_high",
    "vol_20", "vol_60", "atr_pct_14", "max_dd_120",
    "rel_volume_20", "amihud_20", "rsi_14", "adx_14",
]

_MARKET: list[FeatureSpec] = [
    FeatureSpec("mkt_ret_20", "market", 20, "pct"),
    FeatureSpec("mkt_ret_60", "market", 60, "pct"),
    FeatureSpec("mkt_breadth_50", "market", 50, "raw"),
    FeatureSpec("mkt_vol_20", "market", 20, "raw"),
    FeatureSpec("sector_rel_ret_20", "sector", 20, "raw"),
    FeatureSpec("sector_rel_ret_60", "sector", 60, "raw"),
]

FEATURE_SPECS: list[FeatureSpec] = (
    _RAW
    + [FeatureSpec(f"{n}_z", "cross_sectional", s.lookback, "zscore_xs")
       for n in _XS_SOURCE for s in _RAW if s.name == n]
    + [FeatureSpec(f"{n}_pr", "cross_sectional", s.lookback, "pct_rank_xs")
       for n in _XS_SOURCE for s in _RAW if s.name == n]
    + _MARKET
)

FEATURE_NAMES: list[str] = [s.name for s in FEATURE_SPECS]
MAX_LOOKBACK: int = max(s.lookback for s in FEATURE_SPECS)


def _safe(x: float) -> float:
    return float(x) if x is not None and math.isfinite(x) else 0.0


def _ret(a: np.ndarray, n: int) -> float:
    if len(a) < n + 1 or a[-1 - n] == 0:
        return 0.0
    return _safe(a[-1] / a[-1 - n] - 1.0)


def raw_features(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, volumes: np.ndarray
) -> dict[str, float]:
    """All per-symbol raw features at the last bar of the (causal) arrays."""
    c, h, low, v = (np.asarray(x, dtype=float) for x in (closes, highs, lows, volumes))
    n = len(c)
    out: dict[str, float] = dict.fromkeys((s.name for s in _RAW), 0.0)
    if n < 3:
        return out
    cl = c.tolist()
    rets = np.diff(c) / np.where(c[:-1] == 0, np.nan, c[:-1])

    for k in (1, 5, 10, 20, 60, 120):
        out[f"ret_{k}"] = _ret(c, k)
    out["mom_accel"] = _ret(c, 20) - _ret(c[:-20], 20) if n > 41 else 0.0
    for p in (20, 50, 100, 200):
        m = sma(cl, p)
        out[f"dist_sma{p}"] = _safe(c[-1] / m - 1.0) if m else 0.0
    if n > 25:
        m_now, m_prev = sma(cl, 20), sma(cl[:-5], 20)
        out["sma20_slope"] = _safe(m_now / m_prev - 1.0) if m_now and m_prev else 0.0
    e12, e26 = ema(cl, 12), ema(cl, 26)
    out["ema_spread"] = _safe((e12 - e26) / e26) if e12 and e26 else 0.0
    win = c[-252:] if n >= 252 else c
    out["dist_52w_high"] = _safe(c[-1] / win.max() - 1.0) if win.max() else 0.0
    tail = rets[-60:]
    tail = tail[np.isfinite(tail)]
    out["trend_persistence"] = _safe(np.mean(tail > 0) - 0.5) * 2.0 if tail.size else 0.0

    for k in (20, 60):
        seg = rets[-k:]
        seg = seg[np.isfinite(seg)]
        out[f"vol_{k}"] = _safe(np.std(seg)) if seg.size > 2 else 0.0
    a = atr(list(h), list(low), cl, 14)
    out["atr_pct_14"] = _safe(a / c[-1]) if a and c[-1] else 0.0
    if n >= 21:
        lr = np.log(np.where(low[-20:] == 0, np.nan, h[-20:] / np.where(low[-20:] == 0, np.nan, low[-20:])))
        lr = lr[np.isfinite(lr)]
        out["parkinson_20"] = _safe(math.sqrt(np.mean(lr**2) / (4 * math.log(2)))) if lr.size else 0.0
    dn = rets[-20:]
    dn = dn[np.isfinite(dn)]
    out["downside_dev_20"] = _safe(np.std(np.minimum(dn, 0.0))) if dn.size > 2 else 0.0
    seg = c[-120:] if n >= 120 else c
    peak = np.maximum.accumulate(seg)
    out["max_dd_120"] = _safe((seg / peak - 1.0).min()) if peak.min() > 0 else 0.0

    vpos = v[v > 0]
    if vpos.size >= 20:
        m20 = v[-20:].mean()
        out["rel_volume_20"] = _safe(v[-1] / m20) if m20 else 0.0
    if n >= 61:
        seg = v[-60:]
        sd = seg.std()
        out["volume_z_60"] = _safe((v[-1] - seg.mean()) / sd) if sd else 0.0
        h1, h2 = v[-60:-30].mean(), v[-30:].mean()
        out["turnover_accel"] = _safe(h2 / h1 - 1.0) if h1 else 0.0
    m = min(20, len(rets))
    val = (c[-m:] * v[-m:])
    r20 = np.abs(rets[-m:])
    mask = (val > 0) & np.isfinite(r20)
    if mask.any():
        out["amihud_20"] = _safe(float(np.mean(r20[mask] / val[mask])) * 1e9)

    out["rsi_14"] = _safe((rsi(cl, 14) or 50.0) - 50.0)
    e12s = _ema_last_series(cl, 12)
    e26s = _ema_last_series(cl, 26)
    if e12s is not None and e26s is not None:
        macd_line = e12s - e26s
        sig = _ema_of(macd_line, 9)
        out["macd_hist_norm"] = _safe((macd_line[-1] - sig) / c[-1]) if sig is not None and c[-1] else 0.0
    out["adx_14"] = _safe(adx(list(h), list(low), cl, 14) or 0.0)
    bb = bollinger(cl, 20, 2.0)
    if bb:
        lo, mid, hi = bb
        out["bb_pos_20"] = _safe((c[-1] - lo) / (hi - lo) - 0.5) * 2.0 if hi > lo else 0.0
    if n >= 14:
        ll, hh = low[-14:].min(), h[-14:].max()
        out["stoch_k_14"] = _safe((c[-1] - ll) / (hh - ll) - 0.5) * 2.0 if hh > ll else 0.0
    return out


def _ema_last_series(values: list[float], period: int) -> np.ndarray | None:
    if len(values) < period:
        return None
    a = np.asarray(values, dtype=float)
    k = 2.0 / (period + 1.0)
    out = np.empty_like(a)
    out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


def _ema_of(arr: np.ndarray, period: int) -> float | None:
    if arr is None or len(arr) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = arr[0]
    for x in arr[1:]:
        e = x * k + e * (1 - k)
    return float(e)


def _zscore(x: np.ndarray) -> np.ndarray:
    m, s = np.nanmean(x), np.nanstd(x)
    if not math.isfinite(s) or s == 0:
        return np.zeros_like(x)
    return np.clip((x - m) / s, -5.0, 5.0)


def _pct_rank(x: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(x))
    return order / max(len(x) - 1, 1)


class FeaturePipeline:
    """Batch feature panel builder. Stateless; safe to reuse."""

    specs = FEATURE_SPECS
    names = FEATURE_NAMES

    def cross_section(
        self,
        raw_by_symbol: dict[str, dict[str, float]],
        *,
        sector_by_symbol: dict[str, str],
    ) -> dict[str, dict[str, float]]:
        """Add cross-sectional + market/sector columns to each symbol's row."""
        syms = list(raw_by_symbol)
        if not syms:
            return {}
        rows = {s: dict(raw_by_symbol[s]) for s in syms}

        for src in _XS_SOURCE:
            vals = np.array([raw_by_symbol[s].get(src, 0.0) for s in syms], dtype=float)
            z, pr = _zscore(vals), _pct_rank(vals)
            for i, s in enumerate(syms):
                rows[s][f"{src}_z"] = float(z[i])
                rows[s][f"{src}_pr"] = float(pr[i])

        mkt_r20 = float(np.mean([raw_by_symbol[s].get("ret_20", 0.0) for s in syms]))
        mkt_r60 = float(np.mean([raw_by_symbol[s].get("ret_60", 0.0) for s in syms]))
        breadth = float(np.mean([raw_by_symbol[s].get("dist_sma50", 0.0) > 0 for s in syms]))
        mkt_vol = float(np.mean([raw_by_symbol[s].get("vol_20", 0.0) for s in syms]))

        sect_r20: dict[str, list[float]] = {}
        sect_r60: dict[str, list[float]] = {}
        for s in syms:
            sect_r20.setdefault(sector_by_symbol.get(s, "?"), []).append(
                raw_by_symbol[s].get("ret_20", 0.0))
            sect_r60.setdefault(sector_by_symbol.get(s, "?"), []).append(
                raw_by_symbol[s].get("ret_60", 0.0))
        sect_m20 = {k: float(np.mean(v)) for k, v in sect_r20.items()}
        sect_m60 = {k: float(np.mean(v)) for k, v in sect_r60.items()}

        for s in syms:
            sect = sector_by_symbol.get(s, "?")
            rows[s]["mkt_ret_20"] = mkt_r20
            rows[s]["mkt_ret_60"] = mkt_r60
            rows[s]["mkt_breadth_50"] = breadth
            rows[s]["mkt_vol_20"] = mkt_vol
            rows[s]["sector_rel_ret_20"] = raw_by_symbol[s].get("ret_20", 0.0) - sect_m20.get(sect, 0.0)
            rows[s]["sector_rel_ret_60"] = raw_by_symbol[s].get("ret_60", 0.0) - sect_m60.get(sect, 0.0)
        for s in syms:
            for name in self.names:
                rows[s].setdefault(name, 0.0)
        return rows

    def panel(
        self,
        bars_by_symbol: dict[str, list[Any]],
        *,
        rebalance_dates: list[date],
        sector_by_symbol: dict[str, str],
        min_symbols: int = 10,
    ) -> pd.DataFrame:
        """Feature matrix indexed by (rebalance_date, symbol).

        For each date, each symbol's arrays are sliced to bars strictly on
        or before that date, so no future information enters a row.
        """
        # pre-index each symbol's bars by date once
        by_sym: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        for sym, bars in bars_by_symbol.items():
            ds = np.array([_bar_date(b) for b in bars])
            by_sym[sym] = (
                ds,
                np.array([float(b.close) for b in bars]),
                np.array([float(b.high) for b in bars]),
                np.array([float(b.low) for b in bars]),
                np.array([float(b.volume or 0.0) for b in bars]),
            )

        records: list[dict[str, Any]] = []
        for d in rebalance_dates:
            raw_by_symbol: dict[str, dict[str, float]] = {}
            for sym, (ds, c, h, low, v) in by_sym.items():
                m = ds <= d
                k = int(m.sum())
                if k <= MAX_LOOKBACK // 4:
                    continue
                raw_by_symbol[sym] = raw_features(c[m], h[m], low[m], v[m])
            if len(raw_by_symbol) < min_symbols:
                continue
            xs = self.cross_section(raw_by_symbol, sector_by_symbol=sector_by_symbol)
            for sym, row in xs.items():
                rec = {"date": pd.Timestamp(d), "symbol": sym}
                rec.update({name: row.get(name, 0.0) for name in self.names})
                records.append(rec)
        if not records:
            return pd.DataFrame(columns=["date", "symbol", *self.names]).set_index(["date", "symbol"])
        return pd.DataFrame.from_records(records).set_index(["date", "symbol"]).sort_index()

    def spec_table(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self.specs]


def _bar_date(b: Any) -> date:
    from app.chinese_transformer.data_quality import _ts_to_date

    d = _ts_to_date(getattr(b, "timestamp", None))
    return d or date.min

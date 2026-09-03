"""Per-strategy dynamic universe screens.

The leaderboard used to test every strategy on the same fixed basket. That
is unfair: a mean-reversion system and a trend follower do not want the same
stocks. Each screen here takes an already-fetched, *causal* bar dict (bars
dated on/before ``as_of`` only) and returns the subset of names that fits a
particular kind of strategy, together with a plain-English rationale that is
frozen into the backtest result so the catalog can show *why* those names
were chosen.

Screens are pure functions over data the caller already holds, so resolving
a test plan costs no broker calls.

SURVIVORSHIP CAVEAT — the candidate set is *today's* listed, liquid NSE cash
market. NSE exposes no point-in-time index membership, delisting dates or
IPO dates through the data this platform has, so a historical screen
over-represents survivors. This is disclosed on every result.
"""

from __future__ import annotations

import inspect
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.market_data.nse_universe import SECTOR_INDICES
from app.strategies.base import Bar
from app.strategies.indicators import adx

_SURVIVORSHIP = (
    "Candidate set is today's listed, liquid NSE cash market; NSE exposes no "
    "point-in-time membership, so a historical screen over-represents survivors."
)


@dataclass(frozen=True)
class ScreenResult:
    symbols: list[str]
    rationale: str
    metrics: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "rationale": self.rationale,
            "metrics": self.metrics,
            "caveats": self.caveats,
        }


# --------------------------------------------------------------------------
# numeric helpers (numpy only)
# --------------------------------------------------------------------------

def _closes(bars: Sequence[Bar]) -> np.ndarray:
    return np.asarray([float(b.close) for b in bars], dtype=float)


def _log_returns(bars: Sequence[Bar], window: int | None = None) -> np.ndarray:
    c = _closes(bars)
    if window is not None:
        c = c[-(window + 1):]
    c = c[c > 0]
    if len(c) < 3:
        return np.asarray([], dtype=float)
    return np.diff(np.log(c))


def _median_turnover(bars: Sequence[Bar], window: int) -> float:
    tail = bars[-window:]
    if not tail:
        return 0.0
    vals = [float(b.close) * float(b.volume) for b in tail if b.close and b.volume]
    return float(np.median(vals)) if vals else 0.0


def _ann_vol(bars: Sequence[Bar], window: int) -> float:
    r = _log_returns(bars, window)
    return float(np.std(r) * np.sqrt(252.0)) if len(r) > 5 else 0.0


def _lag1_autocorr(r: np.ndarray) -> float:
    if len(r) < 20:
        return 0.0
    a, b = r[:-1], r[1:]
    sa, sb = np.std(a), np.std(b)
    if sa == 0 or sb == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _hurst(r: np.ndarray) -> float:
    """Rescaled-range Hurst estimate. <0.5 mean-reverting, >0.5 trending."""
    n = len(r)
    if n < 64:
        return 0.5
    lags = [8, 16, 32, min(64, n // 2)]
    rs: list[float] = []
    for lag in lags:
        chunks = n // lag
        if chunks < 1:
            continue
        vals = []
        for i in range(chunks):
            seg = r[i * lag:(i + 1) * lag]
            z = seg - seg.mean()
            cumdev = np.cumsum(z)
            spread = cumdev.max() - cumdev.min()
            sd = seg.std()
            if sd > 0:
                vals.append(spread / sd)
        if vals:
            rs.append(np.mean(vals))
    if len(rs) < 2:
        return 0.5
    poly = np.polyfit(np.log(lags[:len(rs)]), np.log(rs), 1)
    return float(np.clip(poly[0], 0.0, 1.0))


def _adx_median(bars: Sequence[Bar], period: int, window: int) -> float:
    tail = bars[-(window + period + 1):]
    highs = [float(b.high) for b in tail]
    lows = [float(b.low) for b in tail]
    closes = [float(b.close) for b in tail]
    out: list[float] = []
    step = max(1, len(closes) // 40)
    for end in range(period * 3, len(closes), step):
        v = adx(highs[:end], lows[:end], closes[:end], period)
        if v is not None:
            out.append(v)
    return float(np.median(out)) if out else 0.0


def _adf_tstat(resid: np.ndarray) -> tuple[float, float]:
    """Hand-rolled Augmented Dickey-Fuller (constant, 1 lag). Returns
    ``(t_stat, half_life_days)``. More negative t = more stationary."""
    y = resid
    dy = np.diff(y)
    ylag = y[:-1]
    dylag = dy[:-1]
    dy = dy[1:]
    ylag = ylag[1:]
    x = np.column_stack([np.ones_like(ylag), ylag, dylag])
    beta, *_ = np.linalg.lstsq(x, dy, rcond=None)
    fitted = x @ beta
    dof = len(dy) - x.shape[1]
    if dof <= 0:
        return 0.0, np.inf
    sigma2 = float((dy - fitted) @ (dy - fitted) / dof)
    xtx_inv = np.linalg.inv(x.T @ x)
    se_gamma = float(np.sqrt(sigma2 * xtx_inv[1, 1]))
    gamma = float(beta[1])
    t = gamma / se_gamma if se_gamma > 0 else 0.0
    half_life = float(-np.log(2.0) / np.log(1.0 + gamma)) if -1.0 < gamma < 0.0 else np.inf
    return t, half_life


# --------------------------------------------------------------------------
# base liquidity filter
# --------------------------------------------------------------------------

def _eligible(
    bars: dict[str, list[Bar]], *, min_price: float, min_bars: int,
) -> list[str]:
    out = []
    for sym, bs in bars.items():
        if len(bs) < min_bars:
            continue
        if float(bs[-1].close) < min_price:
            continue
        out.append(sym)
    return out


def liquid_base(
    bars: dict[str, list[Bar]], as_of: date, *,
    n: int = 120, min_price: float = 30.0, min_bars: int = 260,
    turnover_window: int = 120,
) -> ScreenResult:
    elig = _eligible(bars, min_price=min_price, min_bars=min_bars)
    ranked = sorted(elig, key=lambda s: _median_turnover(bars[s], turnover_window), reverse=True)
    picked = ranked[:n]
    if picked:
        lo = _median_turnover(bars[picked[-1]], turnover_window) / 1e7
        rationale = (
            f"The {len(picked)} most liquid NSE cash names as of {as_of:%d %b %Y} "
            f"(median daily turnover down to about ₹{lo:.0f} cr), priced over "
            f"₹{min_price:.0f} with at least {min_bars} clean daily bars. "
            "This is the tradeable base every other screen filters further."
        )
    else:
        rationale = "No names cleared the liquidity / price / history filter."
    return ScreenResult(picked, rationale,
                        {"candidates": len(elig), "selected": len(picked)},
                        [_SURVIVORSHIP])


def _base_syms(bars: dict[str, list[Bar]], as_of: date, base_n: int) -> list[str]:
    return liquid_base(bars, as_of, n=base_n).symbols


# --------------------------------------------------------------------------
# strategy-shaped screens
# --------------------------------------------------------------------------

def mean_reverting(
    bars: dict[str, list[Bar]], as_of: date, *,
    n: int = 40, base_n: int = 150, ac_window: int = 252,
) -> ScreenResult:
    base = _base_syms(bars, as_of, base_n)
    scored: list[tuple[str, float, float]] = []
    for s in base:
        r = _log_returns(bars[s], ac_window)
        if len(r) < 60:
            continue
        scored.append((s, _lag1_autocorr(r), _hurst(r)))
    scored.sort(key=lambda t: (t[1], t[2]))          # most negative autocorr first
    picked = [s for s, _a, _h in scored[:n]]
    chosen_ac = np.median([a for _s, a, _h in scored[:n]]) if picked else 0.0
    rest_ac = np.median([a for _s, a, _h in scored[n:]]) if len(scored) > n else 0.0
    chosen_h = np.median([h for _s, _a, h in scored[:n]]) if picked else 0.5
    rationale = (
        f"Mean-reversion systems (RSI-2, Bollinger fade, z-score) only have an "
        f"edge on names that actually revert. Of {len(scored)} liquid names these "
        f"{len(picked)} have the most negative 1-day return autocorrelation "
        f"(median {chosen_ac:+.3f} vs {rest_ac:+.3f} for the rest) and a median "
        f"Hurst of {chosen_h:.2f} (< 0.5 = a down day tends to be followed by an "
        f"up day). Trending names are deliberately excluded."
    )
    return ScreenResult(picked, rationale,
                        {"candidates": len(scored), "selected": len(picked),
                         "median_lag1_autocorr": round(chosen_ac, 4),
                         "median_hurst": round(chosen_h, 3)},
                        [_SURVIVORSHIP])


def trend_persistent(
    bars: dict[str, list[Bar]], as_of: date, *,
    n: int = 40, base_n: int = 150,
) -> ScreenResult:
    base = _base_syms(bars, as_of, base_n)
    scored: list[tuple[str, float, float]] = []
    for s in base:
        r = _log_returns(bars[s], 252)
        if len(r) < 120:
            continue
        scored.append((s, _adx_median(bars[s], 14, 200), _hurst(r)))
    if scored:
        adx_rank = {s: i for i, (s, _a, _h) in
                    enumerate(sorted(scored, key=lambda t: t[1], reverse=True))}
        hur_rank = {s: i for i, (s, _a, _h) in
                    enumerate(sorted(scored, key=lambda t: t[2], reverse=True))}
        composite = sorted(scored, key=lambda t: adx_rank[t[0]] + hur_rank[t[0]])
    else:
        composite = []
    picked = [s for s, _a, _h in composite[:n]]
    med_adx = np.median([a for _s, a, _h in composite[:n]]) if picked else 0.0
    med_h = np.median([h for _s, _a, h in composite[:n]]) if picked else 0.5
    rationale = (
        f"Trend and breakout systems (Supertrend, Donchian, golden cross, "
        f"52-week-high) bleed in chop. Of {len(scored)} liquid names these "
        f"{len(picked)} trend the hardest — highest blend of median ADX(14) "
        f"({med_adx:.0f}) and Hurst ({med_h:.2f} > 0.5 = moves persist)."
    )
    return ScreenResult(picked, rationale,
                        {"candidates": len(scored), "selected": len(picked),
                         "median_adx": round(med_adx, 1), "median_hurst": round(med_h, 3)},
                        [_SURVIVORSHIP])


def _vol_screen(
    bars: dict[str, list[Bar]], as_of: date, *, n: int, base_n: int,
    vol_window: int, high: bool,
) -> ScreenResult:
    base = _base_syms(bars, as_of, base_n)
    scored = [(s, _ann_vol(bars[s], vol_window)) for s in base]
    scored = [(s, v) for s, v in scored if v > 0]
    scored.sort(key=lambda t: t[1], reverse=high)
    picked = [s for s, _v in scored[:n]]
    band = np.median([v for _s, v in scored[:n]]) if picked else 0.0
    if high:
        rationale = (
            f"Volatility / breakout strategies need range to work with. These "
            f"{len(picked)} of {len(scored)} liquid names sit in the top realised-"
            f"volatility band (median {band * 100:.0f}% annualised over "
            f"{vol_window} days)."
        )
    else:
        rationale = (
            f"The low-volatility anomaly buys the calmest names. These "
            f"{len(picked)} of {len(scored)} liquid names sit in the bottom "
            f"realised-volatility band (median {band * 100:.0f}% annualised over "
            f"{vol_window} days)."
        )
    return ScreenResult(picked, rationale,
                        {"candidates": len(scored), "selected": len(picked),
                         "median_ann_vol_pct": round(band * 100, 1)},
                        [_SURVIVORSHIP])


def high_volatility(bars, as_of, *, n: int = 40, base_n: int = 150, vol_window: int = 120):
    return _vol_screen(bars, as_of, n=n, base_n=base_n, vol_window=vol_window, high=True)


def low_volatility(bars, as_of, *, n: int = 40, base_n: int = 200, vol_window: int = 120):
    return _vol_screen(bars, as_of, n=n, base_n=base_n, vol_window=vol_window, high=False)


def broad_cross_section(
    bars: dict[str, list[Bar]], as_of: date, *, n: int = 120,
) -> ScreenResult:
    res = liquid_base(bars, as_of, n=n)
    rationale = (
        f"Cross-sectional rank strategies (momentum, multi-factor, dual "
        f"momentum) score every name against the field, so they need the whole "
        f"liquid cross-section — here the {len(res.symbols)} most liquid NSE "
        f"names as of {as_of:%d %b %Y}, not a pre-filtered slice."
    )
    return ScreenResult(res.symbols, rationale, res.metrics, res.caveats)


def consolidation_prone(
    bars: dict[str, list[Bar]], as_of: date, *,
    n: int = 40, base_n: int = 150, window: int = 25, tight_pct: float = 15.0,
    history: int = 500,
) -> ScreenResult:
    base = _base_syms(bars, as_of, base_n)
    scored: list[tuple[str, float]] = []
    for s in base:
        bs = bars[s][-history:]
        if len(bs) < window * 3:
            continue
        highs = np.asarray([float(b.high) for b in bs])
        lows = np.asarray([float(b.low) for b in bs])
        closes = np.asarray([float(b.close) for b in bs])
        tight = 0
        total = 0
        for i in range(window, len(bs), max(1, window // 3)):
            seg_h = highs[i - window:i].max()
            seg_l = lows[i - window:i].min()
            mid = closes[i - window:i].mean()
            if mid > 0:
                total += 1
                if (seg_h - seg_l) / mid * 100.0 <= tight_pct:
                    tight += 1
        if total:
            scored.append((s, tight / total))
    scored.sort(key=lambda t: t[1], reverse=True)
    picked = [s for s, _f in scored[:n]]
    frac = np.median([f for _s, f in scored[:n]]) if picked else 0.0
    rationale = (
        f"A volatility-contraction breakout only sets up on names that actually build tight "
        f"bases. Of {len(scored)} liquid names these {len(picked)} spend the most time coiled "
        f"— a median {frac * 100:.0f}% of rolling {window}-bar windows sit inside a "
        f"{tight_pct:.0f}% range."
    )
    return ScreenResult(picked, rationale,
                        {"candidates": len(scored), "selected": len(picked),
                         "median_tight_fraction": round(float(frac), 3)},
                        [_SURVIVORSHIP])


def seasonal_sector_stock_leaders(
    bars: dict[str, list[Bar]], as_of: date, *,
    n: int = 120, min_quality: float = 45.0, min_valuation: float = 0.0,
    apply_fundamental_gate: bool = True, settings: Any = None,
) -> ScreenResult:
    """Liquid stocks that clear a current-fundamentals quality gate, plus every
    sector index — the strategy classifies each stock to a sector by
    correlation and rotates monthly into the technically-strongest names within
    the month's seasonally-favoured sectors."""
    base = _base_syms(bars, as_of, n)
    kept: list[str] = []
    no_data = 0
    q_vals: list[float] = []
    if apply_fundamental_gate and settings is not None:
        from app.market_scanner import fundamentals as fnd

        for s in base:
            try:
                fv = fnd.view(settings, s)
            except Exception:  # noqa: BLE001 - a bad fundamentals fetch must not sink the screen
                fv = None
            if fv is None or not fv.available or fv.quality is None:
                no_data += 1
                kept.append(s)                      # don't punish a data gap
                continue
            q_vals.append(fv.quality)
            if fv.quality >= min_quality and (fv.valuation or 0.0) >= min_valuation:
                kept.append(s)
    else:
        kept = list(base)

    sectors = [s for s in SECTOR_INDICES if len(bars.get(s, [])) >= 260]
    extras = [*sectors]
    if len(bars.get("NIFTY 50", [])) >= 260:
        extras.append("NIFTY 50")             # market-regime gate yardstick
    syms = kept + [s for s in extras if s not in kept]
    med_q = float(np.median(q_vals)) if q_vals else None
    gate = (f"pass a current-fundamentals quality gate (>= {min_quality:.0f}"
            + (f", valuation >= {min_valuation:.0f}" if min_valuation > 0 else "") + ")")
    rationale = (
        f"Of {len(base)} liquid names, {len(kept)} {gate}"
        + (f" (median quality {med_q:.0f}; {no_data} had no fundamentals and were kept)"
           if q_vals else "")
        + f". Paired with the {len(sectors)} NSE sector indices; the strategy rotates monthly "
        "into the technically-strongest of these stocks inside each month's seasonally-favoured "
        "sectors."
    )
    caveats = [_SURVIVORSHIP,
               "The fundamental gate uses present-day data (no point-in-time fundamentals are "
               "available) — a mild look-ahead on which companies are 'quality'."]
    return ScreenResult(syms, rationale,
                        {"candidates": len(base), "fundamental_pass": len(kept),
                         "no_fundamentals": no_data, "median_quality": (
                             round(med_q, 1) if med_q is not None else None),
                         "sectors": len(sectors)},
                        caveats)


def leaders_with_benchmark(
    bars: dict[str, list[Bar]], as_of: date, *,
    n: int = 60, benchmark: str = "NIFTY 50", min_bars: int = 260,
) -> ScreenResult:
    base = _base_syms(bars, as_of, n)
    syms = [s for s in base if s != benchmark]
    if len(bars.get(benchmark, [])) >= min_bars:
        syms.append(benchmark)
    rationale = (
        f"Relative-strength leadership is measured against an index, so this runs the "
        f"{len(syms) - 1} most liquid names *plus* {benchmark} as the yardstick — the "
        f"strategy needs both legs on every bar."
    )
    return ScreenResult(syms, rationale,
                        {"selected": len(syms), "benchmark": benchmark}, [_SURVIVORSHIP])


def sector_index_basket(
    bars: dict[str, list[Bar]], as_of: date, *, min_bars: int = 260,
    benchmark: str = "NIFTY 50",
) -> ScreenResult:
    present = [s for s in SECTOR_INDICES if len(bars.get(s, [])) >= min_bars]
    syms = list(present)
    if len(bars.get(benchmark, [])) >= min_bars and benchmark not in syms:
        syms.append(benchmark)                # for the market-regime gate
    rationale = (
        f"Sector-rotation trades the {len(present)} NSE sector indices "
        f"themselves, not single stocks, so idiosyncratic company noise does "
        f"not swamp the relative-strength signal"
        + (f"; {benchmark} is included as the market-regime yardstick"
           if benchmark in syms else "") + "."
    )
    return ScreenResult(syms, rationale,
                        {"candidates": len(SECTOR_INDICES), "selected": len(present)},
                        ["Sector indices are not directly tradable; treat as sector-ETF proxies."])


def index_proxy(
    bars: dict[str, list[Bar]], as_of: date, *, which: tuple[str, ...] = ("NIFTY 50",),
) -> ScreenResult:
    present = [s for s in which if bars.get(s)]
    rationale = (
        "Calendar / overnight-drift effects are index-level phenomena, so this "
        f"runs on {', '.join(present) or 'the broad index'} as a single "
        "instrument rather than a stock basket."
    )
    return ScreenResult(present, rationale, {"selected": len(present)}, [])


def cointegrated_pair(
    bars: dict[str, list[Bar]], as_of: date, *,
    base_n: int = 30, window: int = 252, max_half_life: float = 60.0,
    adf_max: float = -3.0,
) -> ScreenResult:
    base = [s for s in _base_syms(bars, as_of, base_n) if len(bars[s]) >= window + 5]
    series = {s: np.log(_closes(bars[s])[-window:]) for s in base}
    best: tuple[float, float, str, str, float] | None = None
    tested = 0
    for a, b in itertools.combinations(sorted(series), 2):
        ya, yb = series[a], series[b]
        if len(ya) != len(yb):
            continue
        tested += 1
        x = np.column_stack([np.ones_like(yb), yb])
        beta, *_ = np.linalg.lstsq(x, ya, rcond=None)
        resid = ya - x @ beta
        t, hl = _adf_tstat(resid)
        # a fast-reverting spread (sub-day half-life) is good, not a defect;
        # only reject non-reverting (inf) or glacially slow spreads.
        if not np.isfinite(hl) or hl <= 0.05 or hl > max_half_life:
            continue
        if t > adf_max:                       # not stationary enough to trade
            continue
        if best is None or t < best[0]:
            best = (t, hl, a, b, float(beta[1]))
    if best is None:
        return ScreenResult(
            [],
            f"No pair in the {len(base)} most liquid names has a spread stationary "
            f"enough to trade (ADF t below {adf_max}) as of {as_of:%d %b %Y}.",
            {"pairs_tested": tested}, [_SURVIVORSHIP])
    t, hl, a, b, hedge = best
    rationale = (
        f"Pairs trading needs two names whose spread mean-reverts. Of {tested} "
        f"candidate pairs among the {len(base)} most liquid names, {a}–{b} has "
        f"the most stationary log-price spread as of {as_of:%d %b %Y} "
        f"(ADF t {t:.2f}, hedge ratio {hedge:.2f}, about {hl:.0f}-day half-life)."
    )
    return ScreenResult([a, b], rationale,
                        {"pairs_tested": tested, "adf_tstat": round(t, 2),
                         "half_life_days": round(hl, 1), "hedge_ratio": round(hedge, 3)},
                        [_SURVIVORSHIP])


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

Screen = Callable[..., ScreenResult]

SCREENS: dict[str, Screen] = {
    "liquid_base": liquid_base,
    "mean_reverting": mean_reverting,
    "trend_persistent": trend_persistent,
    "high_volatility": high_volatility,
    "low_volatility": low_volatility,
    "broad_cross_section": broad_cross_section,
    "consolidation_prone": consolidation_prone,
    "seasonal_sector_stock_leaders": seasonal_sector_stock_leaders,
    "leaders_with_benchmark": leaders_with_benchmark,
    "sector_index_basket": sector_index_basket,
    "index_proxy": index_proxy,
    "cointegrated_pair": cointegrated_pair,
}


def run_screen(
    name: str, bars: dict[str, list[Bar]], as_of: date,
    params: dict[str, Any] | None = None, *, settings: Any = None,
) -> ScreenResult:
    try:
        fn = SCREENS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown universe screen '{name}' — {sorted(SCREENS)}") from exc
    kwargs = dict(params or {})
    if "settings" in inspect.signature(fn).parameters:
        kwargs["settings"] = settings
    return fn(bars, as_of, **kwargs)

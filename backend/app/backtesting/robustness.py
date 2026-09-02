"""Robustness analytics on top of a completed backtest.

Three independent checks, all deterministic given a seed:

* **Monte Carlo** — resample / reshuffle the realised per-trade P&L to get a
  distribution of terminal return and max drawdown, and probabilities of
  ruin / a drawdown worse than a threshold. Answers "how much of this
  result is luck / path-dependence?".
* **Walk-forward** — split the window into rolling in-sample / out-of-sample
  folds; the orchestrator re-optimises on IS and measures OOS. Here we only
  provide the window maths and the decay/efficiency summary.
* **Parameter sensitivity** — given a metric surface over a swept parameter,
  decide whether the preset sits on a plateau (robust) or a lone spike
  (likely overfit).

The functions here are pure — no engine, no DB. The orchestrator
(:mod:`app.robustness.service`) runs the actual backtests and feeds results
in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _equity_path(pnls: list[float], start: float) -> tuple[float, float, bool]:
    """Return (terminal_return_pct, max_drawdown_pct, ruined)."""
    eq = start
    peak = start
    max_dd = 0.0
    ruined = False
    for p in pnls:
        eq += p
        if eq <= 0:
            ruined = True
            eq = 0.0
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, min(1.0, (peak - eq) / peak))
        if ruined:
            break
    terminal_ret = (eq / start - 1.0) * 100.0 if start > 0 else 0.0
    return max(-100.0, terminal_ret), max_dd * 100.0, ruined


def monte_carlo(
    trade_pnls: list[float],
    *,
    initial_capital: float,
    n_sims: int = 2000,
    seed: int = 12345,
    dd_threshold_pct: float = 20.0,
) -> dict:
    """Bootstrap (resample with replacement) + reshuffle (permute) the trade
    P&L series. Bootstrap probes *magnitude* luck; reshuffle probes *order*
    (path) luck."""
    clean = [float(p) for p in trade_pnls]
    n = len(clean)
    if n < 5:
        return {
            "available": False,
            "reason": f"only {n} closed trades — need >= 5 for a meaningful resample.",
            "n_trades": n,
        }

    rng = random.Random(seed)
    boot_ret: list[float] = []
    boot_dd: list[float] = []
    boot_ruin = 0
    boot_dd_breach = 0
    for _ in range(n_sims):
        sample = [clean[rng.randrange(n)] for _ in range(n)]
        r, dd, ruined = _equity_path(sample, initial_capital)
        boot_ret.append(r)
        boot_dd.append(dd)
        boot_ruin += ruined
        boot_dd_breach += dd >= dd_threshold_pct

    shuf_dd: list[float] = []
    shuf_ruin = 0
    for _ in range(n_sims):
        perm = clean[:]
        rng.shuffle(perm)
        _r, dd, ruined = _equity_path(perm, initial_capital)
        shuf_dd.append(dd)
        shuf_ruin += ruined

    boot_ret.sort()
    boot_dd.sort()
    shuf_dd.sort()
    actual_ret, actual_dd, _ = _equity_path(clean, initial_capital)

    return {
        "available": True,
        "n_trades": n,
        "n_sims": n_sims,
        "seed": seed,
        "dd_threshold_pct": dd_threshold_pct,
        "actual_return_pct": round(actual_ret, 2),
        "actual_max_dd_pct": round(actual_dd, 2),
        "bootstrap": {
            "return_pct": {
                "p5": round(_pct(boot_ret, 0.05), 2),
                "p25": round(_pct(boot_ret, 0.25), 2),
                "p50": round(_pct(boot_ret, 0.50), 2),
                "p75": round(_pct(boot_ret, 0.75), 2),
                "p95": round(_pct(boot_ret, 0.95), 2),
            },
            "max_dd_pct": {
                "p50": round(_pct(boot_dd, 0.50), 2),
                "p75": round(_pct(boot_dd, 0.75), 2),
                "p95": round(_pct(boot_dd, 0.95), 2),
            },
            "prob_loss": round(sum(r < 0 for r in boot_ret) / n_sims, 4),
            "prob_ruin": round(boot_ruin / n_sims, 4),
            "prob_dd_beyond_threshold": round(boot_dd_breach / n_sims, 4),
        },
        "reshuffle": {
            "max_dd_pct": {
                "p50": round(_pct(shuf_dd, 0.50), 2),
                "p95": round(_pct(shuf_dd, 0.95), 2),
            },
            "prob_ruin": round(shuf_ruin / n_sims, 4),
        },
    }


def walk_forward_windows(
    start: date, end: date, *, folds: int = 4, oos_frac: float = 0.25, expanding: bool = True
) -> list[dict]:
    """Rolling IS/OOS folds across [start, end].

    The window is split into ``folds`` equal out-of-sample slices covering
    the tail ``folds * oos_frac`` of the span; each fold's in-sample period
    is everything before its OOS slice (expanding) or a fixed-length block
    ending at the OOS slice (rolling).
    """
    total_days = (end - start).days
    if total_days < folds * 30 or folds < 2:
        return []
    oos_days = max(20, int(total_days * oos_frac / folds))
    first_oos_start = end - timedelta(days=oos_days * folds)
    out: list[dict] = []
    is_len = (first_oos_start - start).days
    for k in range(folds):
        oos_s = first_oos_start + timedelta(days=oos_days * k)
        oos_e = oos_s + timedelta(days=oos_days)
        is_s = start if expanding else oos_s - timedelta(days=is_len)
        out.append({
            "fold": k + 1,
            "is_start": is_s.isoformat(),
            "is_end": oos_s.isoformat(),
            "oos_start": oos_s.isoformat(),
            "oos_end": oos_e.isoformat(),
        })
    return out


def walk_forward_summary(folds: list[dict]) -> dict:
    """``folds`` items carry ``is_metrics`` / ``oos_metrics`` dicts (added by
    the orchestrator). Summarise IS→OOS decay and walk-forward efficiency."""
    usable = [f for f in folds if f.get("is_metrics") and f.get("oos_metrics")]
    if not usable:
        return {"available": False, "folds": folds}

    def _m(f: dict, side: str, key: str) -> float:
        return float(f[side].get(key) or 0.0)

    is_sharpes = [_m(f, "is_metrics", "sharpe_ratio") for f in usable]
    oos_sharpes = [_m(f, "oos_metrics", "sharpe_ratio") for f in usable]
    is_rets = [_m(f, "is_metrics", "return_pct") for f in usable]
    oos_rets = [_m(f, "oos_metrics", "return_pct") for f in usable]

    eff = [
        (o / i) for i, o in zip(is_rets, oos_rets, strict=True) if i > 0
    ]
    return {
        "available": True,
        "folds": folds,
        "is_sharpe_mean": round(sum(is_sharpes) / len(is_sharpes), 3),
        "oos_sharpe_mean": round(sum(oos_sharpes) / len(oos_sharpes), 3),
        "sharpe_decay": round(
            (sum(is_sharpes) - sum(oos_sharpes)) / len(usable), 3
        ),
        "oos_profitable_folds": sum(r > 0 for r in oos_rets),
        "total_folds": len(usable),
        "walk_forward_efficiency": round(sum(eff) / len(eff), 3) if eff else None,
    }


@dataclass
class SweepPoint:
    value: float
    sharpe: float
    return_pct: float
    max_dd_pct: float


def sensitivity_verdict(param: str, points: list[SweepPoint], preset_value: float) -> dict:
    """Plateau (robust) vs lone spike (likely overfit)."""
    if len(points) < 3:
        return {"param": param, "available": False, "surface": []}
    pts = sorted(points, key=lambda p: p.value)
    best = max(pts, key=lambda p: p.sharpe)
    sharpes = [p.sharpe for p in pts]
    mean_s = sum(sharpes) / len(sharpes)
    spread = (max(sharpes) - min(sharpes)) or 1e-9

    # neighbours of the best point
    bi = pts.index(best)
    neigh = [pts[i].sharpe for i in (bi - 1, bi + 1) if 0 <= i < len(pts)]
    neigh_drop = (best.sharpe - (sum(neigh) / len(neigh))) / spread if neigh else 0.0

    # where does the preset sit?
    preset_pt = min(pts, key=lambda p: abs(p.value - preset_value))
    preset_rank = sorted(sharpes, reverse=True).index(preset_pt.sharpe) + 1

    overfit_risk = bool(
        neigh_drop > 0.5  # best point's neighbours are much worse -> spike
        and best.sharpe > mean_s + 0.75 * (spread / 2)
    )
    return {
        "param": param,
        "available": True,
        "preset_value": preset_value,
        "preset_sharpe": round(preset_pt.sharpe, 3),
        "preset_rank": preset_rank,
        "best_value": best.value,
        "best_sharpe": round(best.sharpe, 3),
        "neighbour_drop_ratio": round(neigh_drop, 3),
        "overfit_risk": overfit_risk,
        "surface": [
            {"value": p.value, "sharpe": round(p.sharpe, 3),
             "return_pct": round(p.return_pct, 2), "max_dd_pct": round(p.max_dd_pct, 2)}
            for p in pts
        ],
    }

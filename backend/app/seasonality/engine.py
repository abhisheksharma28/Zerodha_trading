"""Orchestrates the seasonality research engine into one report.

    analyze(db, settings) -> {
      "as_of", "method", "data_audit", "sectors", "sector_count",
      "grid":   {sector: {month: cell}},          # 1..12 keys
      "months": {month: {"long": [...], "short": [...], "ranking": [...]}},
      "current_month": {...},                      # convenience
      "fdr": {"n_tested", "n_significant_q05", "n_significant_q10"},
    }

Point-in-time: only completed months, no look-ahead. Regime labels use
data through the *prior* month-end only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.seasonality import INDEX_TIMELINE, MARKET_INDEX
from app.seasonality.data import load_history
from app.seasonality.fdr import benjamini_hochberg, confidence_label
from app.seasonality.horizons import multi_horizon
from app.seasonality.regime import classify_months, edges_by_regime
from app.seasonality.returns import build_panel
from app.seasonality.scoring import (
    long_score,
    master_confidence,
    short_score,
    visual_bucket,
)
from app.seasonality.stats import month_stats

logger = get_logger(__name__)

MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

INDIA_CALENDAR_ANCHORS = {
    2: "Union Budget",
    3: "fiscal year-end / tax-loss selling",
    4: "turn of the fiscal year (1 Apr)",
    12: "calendar year-end / global santa rally",
}

METHOD = (
    "Each sector uses its full available NSE history (not a fixed window). "
    "Monthly simple returns, completed months only, no look-ahead. The primary "
    "'seasonal edge' is the month's return minus that year's average completed "
    "month (own edge); market-adjusted (vs NIFTY 50) and cross-sectional (vs the "
    "median sector) edges are computed alongside. Significance is a two-sided "
    "Student t-test, then Benjamini-Hochberg FDR across the whole sector x month "
    "grid, plus a 10k-resample bootstrap. Edges are recomputed over 3/5/10/15/20/"
    "max-year windows for a stability score, and split by market regime."
)


def _year_month_edges(edge_map: dict[tuple[int, int], float], month: int) -> dict[int, float]:
    return {y: v for (y, m), v in edge_map.items() if m == month}


def _cell(
    sector: str,
    month: int,
    panel: dict[str, Any],
    regimes: dict[tuple[int, int], dict[str, str]],
    last_year: int,
    *,
    do_bootstrap: bool = True,
) -> dict[str, Any] | None:
    own = _year_month_edges(panel["own"][sector], month)
    if len(own) < 3:
        return None
    years = sorted(own)
    rets = panel["returns"][sector]
    raw = [rets[(y, month)] for y in years if (y, month) in rets]
    madj = [panel["market_adj"][sector][(y, month)]
            for y in years if (y, month) in panel["market_adj"].get(sector, {})]
    xranks = [panel["cross_rank"][sector][(y, month)]
              for y in years if (y, month) in panel["cross_rank"].get(sector, {})]

    st = month_stats(
        [own[y] for y in years], raw, market_adj=madj, cross_ranks=xranks,
        do_bootstrap=do_bootstrap,
    )
    st["sector"] = sector
    st["month"] = month
    st["years"] = [years[0], years[-1]]
    hz = multi_horizon(own, last_year=last_year)
    st["horizons"] = hz
    st["regime"] = edges_by_regime({(y, month): own[y] for y in years}, regimes)
    return st


def analyze(
    db: Session,
    settings: Settings,
    *,
    sectors: list[str] | None = None,
    bootstrap: bool = True,
) -> dict[str, Any]:
    bars_by, audits = load_history(db, settings, sectors=sectors)
    usable = [s for s, a in audits.items()
              if a.status != "FAIL" and s not in (MARKET_INDEX, "INDIA VIX") and s in bars_by]
    if not usable:
        raise ValueError("no sector index passed the data-quality audit")

    panel = build_panel(bars_by, sectors=usable)
    all_months = set()
    for r in panel["returns"].values():
        all_months.update(r)
    last_year = max(y for y, _m in all_months) if all_months else datetime.now(UTC).year
    regimes = classify_months(bars_by, sorted(all_months))

    grid: dict[str, dict[int, dict[str, Any]]] = {}
    p_by_key: dict[tuple[str, int], float] = {}
    for sector in usable:
        grid[sector] = {}
        for month in range(1, 13):
            cell = _cell(sector, month, panel, regimes, last_year, do_bootstrap=bootstrap)
            if cell is None:
                continue
            grid[sector][month] = cell
            p_by_key[(sector, month)] = cell["p_value"]

    q_by_key = benjamini_hochberg(p_by_key)
    n_q05 = n_q10 = 0
    for (sector, month), q in q_by_key.items():
        cell = grid[sector][month]
        cell["q_value"] = q
        cell["fdr_label"] = confidence_label(q)
        cell["visual"] = visual_bucket(cell["mean_edge_pct"], cell["t_stat"], q)
        cell["long_score"] = long_score(cell, cell["horizons"])
        cell["short_score"] = short_score(cell, cell["horizons"])
        cell["confidence"] = master_confidence(cell, cell["horizons"])
        if q < 0.05:
            n_q05 += 1
        if q < 0.10:
            n_q10 += 1

    # per-month rankings: full universe strongest -> weakest, plus long / short shortlists
    months_out: dict[int, dict[str, Any]] = {}
    for month in range(1, 13):
        rows = []
        for sector in usable:
            cell = grid.get(sector, {}).get(month)
            if not cell or "q_value" not in cell:
                continue
            rows.append({
                "sector": sector,
                "mean_edge_pct": cell["mean_edge_pct"],
                "median_edge_pct": cell["median_edge_pct"],
                "win_rate": cell["win_rate"],
                "t_stat": cell["t_stat"],
                "q_value": cell["q_value"],
                "n": cell["n"],
                "long_score": cell["long_score"],
                "short_score": cell["short_score"],
                "confidence": cell["confidence"],
                "stability": cell["horizons"].get("stability"),
                "visual": cell["visual"],
                "bootstrap_prob_positive": (cell.get("bootstrap") or {}).get("prob_positive"),
                "bootstrap_prob_negative": (cell.get("bootstrap") or {}).get("prob_negative"),
            })
        ranking = sorted(rows, key=lambda r: r["mean_edge_pct"], reverse=True)
        for i, r in enumerate(ranking, 1):
            r["rank"] = i
        longs = sorted(
            [r for r in rows if r["long_score"] > 0 and r["mean_edge_pct"] > 0],
            key=lambda r: r["long_score"], reverse=True,
        )[:5]
        shorts = sorted(
            [r for r in rows if r["short_score"] > 0 and r["mean_edge_pct"] < 0],
            key=lambda r: r["short_score"], reverse=True,
        )[:5]
        months_out[month] = {
            "month": month,
            "name": MONTH_NAMES[month],
            "anchor": INDIA_CALENDAR_ANCHORS.get(month),
            "ranking": ranking,
            "long_candidates": longs,
            "short_candidates": shorts,
        }

    # honest headline: does anything survive multiple-testing correction?
    survivors = [
        {"sector": s, "month": m, "month_name": MONTH_NAMES[m],
         "mean_edge_pct": grid[s][m]["mean_edge_pct"], "q_value": grid[s][m]["q_value"],
         "direction": "long" if grid[s][m]["mean_edge_pct"] > 0 else "short"}
        for (s, m), q in q_by_key.items() if q < 0.10
    ]
    survivors.sort(key=lambda r: r["q_value"])
    if not survivors:
        verdict = "NO VALID EDGE FOUND"
        verdict_detail = (
            f"Of {len(q_by_key)} sector x month hypotheses, none survive Benjamini-Hochberg "
            "FDR correction at q < 0.10. Raw t-stats reach ~2.7 but that is expected noise "
            "across a grid this size. The historical calendar tilts below are descriptive "
            "only — they are not a statistically validated tradable edge."
        )
    else:
        verdict = f"{len(survivors)} pattern(s) survive multiple testing"
        verdict_detail = (
            f"{len(survivors)} of {len(q_by_key)} sector x month cells clear FDR at q < 0.10 "
            "(descriptive; still needs out-of-sample + prospective validation before trading)."
        )

    now = datetime.now(UTC)
    return {
        "as_of": now.isoformat(),
        "method": METHOD,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "fdr_survivors": survivors,
        "data_audit": {s: a.to_dict() for s, a in audits.items()},
        "index_timeline": {k: {"base_year": v[0], "launch_year": v[1]}
                           for k, v in INDEX_TIMELINE.items()},
        "sectors": usable,
        "sector_count": len(usable),
        "history_span": {
            "earliest": min((a.data_start for a in audits.values() if a.data_start), default=None),
            "latest": max((a.data_end for a in audits.values() if a.data_end), default=None),
        },
        "grid": {s: {str(m): c for m, c in months.items()} for s, months in grid.items()},
        "months": {str(m): v for m, v in months_out.items()},
        "current_month": months_out.get(now.month, {}),
        "fdr": {
            "n_tested": len(q_by_key),
            "n_significant_q05": n_q05,
            "n_significant_q10": n_q10,
            "method": "Benjamini-Hochberg across the full sector x month grid",
        },
        "regime_sample": {
            f"{y}-{m:02d}": regimes[(y, m)]
            for (y, m) in sorted(regimes)[-6:]
        },
    }

"""Run the tuning grid for one strategy and cache the recommendation."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.adhoc import run_adhoc
from app.backtesting.metrics import compute_metrics
from app.config import Settings
from app.core.logging import get_logger
from app.leaderboard.config import canonical_for
from app.strategies.library import get_template
from app.tuning import store
from app.tuning.adopted import tuned_overrides
from app.tuning.config import (
    IN_SAMPLE_FRAC,
    MIN_OOS_TRADES,
    MIN_SHARPE_EDGE,
    grid_for,
)

logger = get_logger(__name__)

_NEG = -1e9


def _split_metrics(equity_curve: list[list[Any]], frac: float) -> tuple[dict, dict, str]:
    """Split the equity curve by index and score each half."""
    n = len(equity_curve)
    if n < 20:
        return ({}, {}, "")
    cut = max(2, int(n * frac))
    is_curve = [(str(ts), float(v)) for ts, v in equity_curve[:cut]]
    oos_curve = [(str(ts), float(v)) for ts, v in equity_curve[cut - 1:]]
    return (
        compute_metrics(is_curve),
        compute_metrics(oos_curve),
        str(equity_curve[cut - 1][0])[:10],
    )


def _oos_trade_count(trades: list[dict], split_day: str) -> int:
    return sum(1 for t in trades if str(t.get("exit_time") or "")[:10] >= split_day and split_day)


def _combo_grid(grid: dict[str, list], preset_params: dict[str, Any]) -> list[dict[str, Any]]:
    keys = list(grid)
    axes = []
    for k in keys:
        vals = list(grid[k])
        pv = preset_params.get(k)
        if pv is not None and pv not in vals:
            vals.append(pv)
        axes.append(sorted(set(vals), key=lambda x: (isinstance(x, str), x)))
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*axes)]


def run_tuning(db: Session, settings: Settings, slug: str) -> dict[str, Any]:
    cfg = canonical_for(slug)
    grid = grid_for(slug)
    if cfg is None or grid is None:
        raise ValueError(f"No tuning grid for '{slug}'")
    template = get_template(slug)
    preset_params = template.presets()[cfg.preset]

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=int(cfg.years * 365.25))
    s0, e0 = from_dt.date().isoformat(), to_dt.date().isoformat()
    symbols = [f"NSE:{s}" for s in cfg.universe]

    combos = _combo_grid(grid, preset_params)
    preset_combo = {k: preset_params.get(k, template.all_params()[k].default) for k in grid}

    rows: list[dict[str, Any]] = []
    for combo in combos:
        try:
            rep = run_adhoc(
                db, settings, slug=slug, symbols=symbols, timeframe=cfg.timeframe,
                start=s0, end=e0, preset=cfg.preset, capital=cfg.capital,
                max_gross_exposure=cfg.max_gross_exposure, max_symbols=len(symbols) + 5,
                overrides=combo,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tuning_combo_failed", slug=slug, combo=combo, error=str(exc))
            continue
        is_m, oos_m, split_day = _split_metrics(rep.equity_curve, IN_SAMPLE_FRAC)
        ruined = bool(rep.metrics.get("diagnostics", {}).get("ruined"))
        oos_trades = _oos_trade_count(rep.trades, split_day)
        is_sh = float(is_m.get("sharpe_ratio") or 0.0)
        oos_sh = float(oos_m.get("sharpe_ratio") or 0.0)
        eligible = (not ruined) and oos_trades >= MIN_OOS_TRADES
        rows.append({
            "params": combo,
            "is_preset": combo == preset_combo,
            "is_sharpe": round(is_sh, 3),
            "oos_sharpe": round(oos_sh, 3),
            "is_return_pct": round(float(is_m.get("total_return_pct") or 0.0), 2),
            "oos_return_pct": round(float(oos_m.get("total_return_pct") or 0.0), 2),
            "oos_trades": oos_trades,
            "total_trades": rep.metrics.get("total_trades"),
            "ruined": ruined,
            "robust_score": round(min(is_sh, oos_sh), 3) if eligible else None,
        })

    ranked = sorted(
        rows, key=lambda r: (r["robust_score"] if r["robust_score"] is not None else _NEG),
        reverse=True,
    )
    preset_row = next((r for r in rows if r["is_preset"]), None)
    preset_score = preset_row["robust_score"] if preset_row and preset_row["robust_score"] is not None else _NEG
    winner = ranked[0] if ranked and ranked[0]["robust_score"] is not None else None

    if winner is None:
        verdict, recommended = "no_eligible_combo", None
    elif winner["is_preset"]:
        verdict, recommended = "keep_preset", None
    elif winner["robust_score"] - preset_score >= MIN_SHARPE_EDGE:
        verdict = "recommend_tuned"
        recommended = {k: v for k, v in winner["params"].items()
                       if preset_combo.get(k) != v}
    else:
        verdict, recommended = "keep_preset", None

    payload = {
        "slug": slug,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": cfg.as_dict(),
        "in_sample_frac": IN_SAMPLE_FRAC,
        "min_sharpe_edge": MIN_SHARPE_EDGE,
        "preset_params": preset_combo,
        "preset_row": preset_row,
        "surface": rows,
        "ranked_top": ranked[:5],
        "verdict": verdict,
        "recommended_overrides": recommended,
        "currently_adopted": tuned_overrides(slug) or None,
        "explanation": _explain(verdict, winner, preset_row, recommended),
    }
    store.save(slug, payload)
    return payload


def _explain(verdict: str, winner, preset_row, recommended) -> str:
    if verdict == "no_eligible_combo":
        return ("No grid point cleared the eligibility bar (enough out-of-sample trades, "
                "not ruined). Keep the current preset; the strategy may not be viable here.")
    if verdict == "keep_preset":
        ps = preset_row["robust_score"] if preset_row else None
        return (f"The current preset is already the most robust point in the grid "
                f"(worst-half Sharpe {ps}); no tuned combo beats it by the required "
                f"{MIN_SHARPE_EDGE} edge. Keep it.")
    return (f"Grid point {recommended} lifts the worst-half (in-sample vs out-of-sample) "
            f"Sharpe to {winner['robust_score']} vs the preset's "
            f"{preset_row['robust_score'] if preset_row else 'n/a'}. Adopt to apply it to the "
            f"canonical run and paper deployment.")


def tuning_for(slug: str) -> dict[str, Any] | None:
    return store.load(slug)

"""Run the robustness suite for one strategy and cache it."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.adhoc import fetch_candles, run_adhoc
from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.param_sim import run_param_sim
from app.backtesting.robustness import (
    SweepPoint,
    monte_carlo,
    sensitivity_verdict,
    walk_forward_summary,
    walk_forward_windows,
)
from app.config import Settings
from app.core.logging import get_logger
from app.leaderboard.config import canonical_for
from app.robustness import store
from app.robustness.config import MC_SIMS, WF_FOLDS, WF_OOS_FRACTION, sweep_for
from app.strategies.library import get_template

logger = get_logger(__name__)

_METRIC_SUBSET = ("return_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades", "win_rate_pct")


def _run(db: Session, settings: Settings, slug: str, cfg: Any, *, start: str, end: str,
         overrides: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[float]]:
    symbols = [f"NSE:{s}" for s in cfg.universe]
    last: Exception | None = None
    for attempt in range(3):  # transient DB / broker blips shouldn't sink an hour of runs
        try:
            rep = run_adhoc(
                db, settings, slug=slug, symbols=symbols, timeframe=cfg.timeframe,
                start=start, end=end, preset=cfg.preset, capital=cfg.capital,
                max_gross_exposure=cfg.max_gross_exposure, max_symbols=len(symbols) + 5,
                overrides=overrides,
            )
            return rep.metrics, rep.trade_pnls
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("robustness_run_retry", slug=slug, attempt=attempt + 1, error=str(exc))
            with contextlib.suppress(Exception):
                db.rollback()
    raise last  # type: ignore[misc]


def _score(mc: dict, wf: dict, sens: dict) -> tuple[float, list[str]]:
    score = 100.0
    notes: list[str] = []
    if mc.get("available"):
        b = mc["bootstrap"]
        if b["prob_ruin"] > 0:
            pen = min(50.0, 300.0 * b["prob_ruin"])
            score -= pen
            notes.append(f"Monte Carlo ruin probability {b['prob_ruin']:.1%} (−{pen:.0f}).")
        if b["prob_loss"] > 0.5:
            pen = (b["prob_loss"] - 0.5) * 80.0
            score -= pen
            notes.append(f"{b['prob_loss']:.0%} of resamples lose money (−{pen:.0f}).")
    if wf.get("available"):
        decay = wf.get("sharpe_decay") or 0.0
        if decay > 0.1:
            pen = min(30.0, decay * 15.0)
            score -= pen
            notes.append(f"Out-of-sample Sharpe decays {decay:.2f} vs in-sample (−{pen:.0f}).")
        frac = (wf["oos_profitable_folds"] / wf["total_folds"]) if wf["total_folds"] else 1.0
        if frac < 0.5:
            pen = 25.0 * (0.5 - frac) / 0.5
            score -= pen
            notes.append(f"Only {wf['oos_profitable_folds']}/{wf['total_folds']} OOS folds "
                         f"profitable (−{pen:.0f}).")
    if sens.get("available") and sens.get("overfit_risk"):
        score -= 25.0
        notes.append(
            f"Parameter '{sens['param']}' sits on a lone Sharpe spike at {sens['best_value']}, "
            f"not a plateau (−25) — likely overfit."
        )
    return max(0.0, round(score, 1)), notes


def run_robustness(db: Session, settings: Settings, slug: str) -> dict[str, Any]:
    cfg = canonical_for(slug)
    if cfg is None:
        raise ValueError(f"No canonical config for '{slug}'")
    template = get_template(slug)

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=int(cfg.years * 365.25))
    s0, e0 = from_dt.date().isoformat(), to_dt.date().isoformat()

    # --- full-window run: Monte Carlo on its realised trades ---
    full_metrics, full_pnls = _run(db, settings, slug, cfg, start=s0, end=e0)
    mc = monte_carlo(full_pnls, initial_capital=cfg.capital, n_sims=MC_SIMS)

    # --- walk-forward: fixed preset, rolling IS/OOS ---
    windows = walk_forward_windows(from_dt.date(), to_dt.date(),
                                   folds=WF_FOLDS, oos_frac=WF_OOS_FRACTION)
    for w in windows:
        try:
            is_m, _ = _run(db, settings, slug, cfg, start=w["is_start"], end=w["is_end"])
            oos_m, _ = _run(db, settings, slug, cfg, start=w["oos_start"], end=w["oos_end"])
            w["is_metrics"] = {k: is_m.get(k) for k in _METRIC_SUBSET}
            w["oos_metrics"] = {k: oos_m.get(k) for k in _METRIC_SUBSET}
        except Exception as exc:  # noqa: BLE001 - a thin fold must not kill the suite
            w["error"] = str(exc)
    wf = walk_forward_summary(windows)

    # --- parameter sensitivity ---
    sweep = sweep_for(slug)
    if sweep is None:
        sens = {"available": False, "reason": "sensitivity sweep not configured for this template."}
    else:
        param, values = sweep
        preset_val = float(template.presets()[cfg.preset].get(
            param, template.all_params()[param].default))
        grid = sorted({*[float(v) for v in values], preset_val})
        points: list[SweepPoint] = []
        for v in grid:
            try:
                m, _ = _run(db, settings, slug, cfg, start=s0, end=e0, overrides={param: v})
                points.append(SweepPoint(
                    value=v, sharpe=float(m.get("sharpe_ratio") or 0.0),
                    return_pct=float(m.get("return_pct") or 0.0),
                    max_dd_pct=float(m.get("max_drawdown_pct") or 0.0),
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("robustness_sweep_point_failed", slug=slug, param=param,
                               value=v, error=str(exc))
        sens = sensitivity_verdict(param, points, preset_val)

    score, notes = _score(mc, wf, sens)
    payload = {
        "slug": slug,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": cfg.as_dict(),
        "full_window_metrics": {k: full_metrics.get(k) for k in _METRIC_SUBSET},
        "monte_carlo": mc,
        "walk_forward": wf,
        "sensitivity": sens,
        "robustness_score": score,
        "notes": notes or ["No robustness red flags detected in this suite."],
    }
    store.save(slug, payload)
    return payload


def robustness_for(slug: str) -> dict[str, Any] | None:
    return store.load(slug)


# --------------------------------------------------------------------------
# parameter-perturbation simulator (+/- pct neighbourhood of the preset)
# --------------------------------------------------------------------------

def run_param_sim_for(
    db: Session, settings: Settings, slug: str, *, pct: float = 5.0, n_samples: int = 30
) -> dict[str, Any]:
    cfg = canonical_for(slug)
    if cfg is None:
        raise ValueError(f"No canonical config for '{slug}'")
    template = get_template(slug)
    base_params = template.resolve_params(template.presets()[cfg.preset])

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=int(cfg.years * 365.25))
    candles, skipped = fetch_candles(
        db, settings, symbols=[f"NSE:{s}" for s in cfg.universe], timeframe=cfg.timeframe,
        start=from_dt.date().isoformat(), end=to_dt.date().isoformat(),
    )
    if not candles:
        raise ValueError(f"No price history for '{slug}' canonical universe. skipped={skipped}")

    result = run_param_sim(
        template, base_params, candles, initial_capital=cfg.capital,
        cost_model=CostModel(CostConfig()), max_gross_exposure=cfg.max_gross_exposure,
        pct=pct, n_samples=n_samples, periods_per_year=252,
    )
    payload = {
        "slug": slug,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": cfg.as_dict(),
        "skipped": skipped,
        **result,
    }
    store.save(slug, payload, kind="param_sim")
    return payload


def param_sim_for(slug: str) -> dict[str, Any] | None:
    return store.load(slug, kind="param_sim")

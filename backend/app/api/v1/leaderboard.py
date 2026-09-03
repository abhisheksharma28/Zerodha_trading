"""Strategy Leaderboard API.

``GET /leaderboard`` is cheap (reads cached canonical runs + live paper
fills). ``POST /leaderboard/refresh`` re-runs the canonical backtests and is
slow (per-strategy dynamic screen + a 5-year backtest), so it now spawns a
detached worker process and returns immediately; poll
``GET /leaderboard/refresh/status`` for progress.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import NotFoundError
from app.leaderboard import (
    CANONICAL,
    catalog,
    ensure_paper_deployments,
    leaderboard,
)
from app.leaderboard import store as lb_store
from app.leaderboard.config import canonical_for
from app.leaderboard.refresh_control import read_status, start_refresh
from app.leaderboard.service import live_paper_stats, sector_seasonality
from app.robustness.service import (
    param_sim_for,
    robustness_for,
    run_param_sim_for,
    run_robustness,
)
from app.tuning import set_runtime_adoption
from app.tuning.config import grid_for
from app.tuning.service import run_tuning, tuning_for

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("")
def get_leaderboard(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    return leaderboard(db, settings)


@router.get("/catalog")
def get_catalog(db: Session = Depends(get_db)) -> dict[str, Any]:
    """The pre-computed backtest showcase: one entry per canonical template
    with metrics + a plain-English summary, read from the on-disk cache.
    Use POST /leaderboard/refresh to (slowly) recompute it."""
    return catalog(db)


@router.get("/seasonality")
def get_sector_seasonality(
    years: float = 10.0,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Month-by-month historical performance of the NSE sector indices over
    the last ``years`` — the table the seasonal-sector-rotation strategy
    trades on. Slow on a cold cache (pulls sector-index history)."""
    return sector_seasonality(db, settings, years=years)


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh(
    slugs: list[str] | None = Body(default=None, embed=True),
) -> dict[str, Any]:
    """Kick a detached refresh of the canonical suite (or the given slugs) and
    return at once. Poll GET /leaderboard/refresh/status. 409 if one is
    already running."""
    return start_refresh(slugs)


@router.get("/refresh/status")
def refresh_status() -> dict[str, Any]:
    """Progress of the running / last refresh: state (idle|running|done|error|
    stalled), completed / total, current slug, per-slug results."""
    return read_status()


@router.post("/refresh/{slug}", status_code=status.HTTP_202_ACCEPTED)
def refresh_one(slug: str) -> dict[str, Any]:
    """Refresh a single canonical strategy, out of process (same status feed)."""
    if slug not in CANONICAL:
        raise NotFoundError(f"'{slug}' is not part of the canonical leaderboard suite.")
    return start_refresh([slug])


@router.post("/paper-deployments")
def create_paper_deployments(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"results": ensure_paper_deployments(db)}


@router.post("/robustness/{slug}")
def run_robustness_suite(
    slug: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Walk-forward + Monte Carlo + parameter-sensitivity for one strategy.
    Slow — runs many backtests — and cached; trigger deliberately."""
    if canonical_for(slug) is None:
        raise NotFoundError(f"'{slug}' is not part of the canonical leaderboard suite.")
    return run_robustness(db, settings, slug)


@router.post("/tune/{slug}")
def run_tuning_grid(
    slug: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Robust grid search over a small parameter grid: each point scored on
    the worse of its in-sample / out-of-sample Sharpe. Slow, cached."""
    if grid_for(slug) is None:
        raise NotFoundError(f"No tuning grid configured for '{slug}'.")
    return run_tuning(db, settings, slug)


@router.post("/tune/{slug}/adopt")
def adopt_tuned_preset(
    slug: str,
    overrides: dict[str, Any] | None = Body(default=None, embed=True),
) -> dict[str, Any]:
    """Persist (``overrides``) or clear (``null``) a tuned override set for
    this strategy. Applied by the next canonical refresh and by newly
    created paper deployments."""
    if grid_for(slug) is None:
        raise NotFoundError(f"'{slug}' has no tuning grid.")
    return {"slug": slug, "adopted": set_runtime_adoption(slug, overrides)}


@router.post("/param-sim/{slug}")
def run_param_sim_endpoint(
    slug: str,
    pct: float = 5.0,
    n_samples: int = 30,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Re-run the canonical backtest ~``n_samples`` times with every numeric
    parameter jittered within +/- ``pct`` percent, and report the KPI
    distribution. Slow, cached."""
    if canonical_for(slug) is None:
        raise NotFoundError(f"'{slug}' is not part of the canonical leaderboard suite.")
    return run_param_sim_for(db, settings, slug, pct=pct, n_samples=n_samples)


@router.get("/{slug}")
def get_detail(slug: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = canonical_for(slug)
    blob = lb_store.load(slug, cfg.config_hash) if cfg else lb_store.load_any(slug)
    if blob is None:
        raise NotFoundError(
            f"No canonical backtest cached for '{slug}'. POST /leaderboard/refresh/{slug} first."
        )
    blob["live"] = live_paper_stats(db, slug)
    blob["robustness"] = robustness_for(slug)
    blob["tuning"] = tuning_for(slug)
    blob["param_sim"] = param_sim_for(slug)
    return blob

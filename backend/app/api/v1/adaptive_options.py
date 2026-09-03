"""Adaptive Options API.

  GET  /config /expiries /strategy-matrix          metadata
  GET|POST /intelligence                           full analysis pipeline
  GET|POST /decision                               + strategy select / size / risk
  POST /backtest                                   walk-forward backtest
  POST /validation                                 walk-forward / MC / sensitivity
  POST /position/evaluate                          leg-management for an open position
  POST /paper/runs  GET /paper/runs  GET|.../{id}  paper trading
  POST /paper/runs/{id}/tick|stop  GET .../decisions
  POST /scheduler/tick                             record snapshots + tick paper runs
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.adaptive_options import paper as _paper
from app.adaptive_options import scheduler as _scheduler
from app.adaptive_options.service import (
    backtest,
    config_presets,
    data_sources,
    evaluate_open_position,
    list_expiries,
    market_intelligence,
    run_decision,
    strategy_matrix,
    validate,
)
from app.config import Settings, get_settings
from app.core.deps import get_db

router = APIRouter(prefix="/adaptive-options", tags=["adaptive-options"])


@router.get("/config")
def get_config() -> dict[str, Any]:
    return config_presets()


@router.get("/expiries")
def get_expiries(underlying: str = "NIFTY", db: Session = Depends(get_db)) -> dict[str, Any]:
    return list_expiries(db, underlying)


@router.get("/intelligence")
def get_intelligence(
    underlying: str = "NIFTY",
    expiry: str | None = None,
    preset: str = "balanced",
    record: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return market_intelligence(
        db, settings, underlying=underlying, expiry=expiry, preset=preset, record=record
    )


@router.post("/intelligence")
def post_intelligence(
    underlying: str = Body("NIFTY", embed=True),
    expiry: str | None = Body(None, embed=True),
    preset: str = Body("balanced", embed=True),
    overrides: dict[str, Any] | None = Body(None, embed=True),
    record: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Same analysis with advanced ``overrides`` on any AdaptiveConfig field."""
    return market_intelligence(
        db, settings, underlying=underlying, expiry=expiry,
        preset=preset, overrides=overrides, record=record,
    )


@router.get("/strategy-matrix")
def get_strategy_matrix(preset: str = "balanced") -> dict[str, Any]:
    """The configurable strategy decision matrix (which regimes / PCR / IV
    each template is built for). Not hard-coded — derived from the library."""
    return strategy_matrix(preset)


@router.get("/data-sources")
def get_data_sources() -> dict[str, Any]:
    """What historical option-chain data the backtest can use right now —
    synthetic (always), NSE bhavcopy (probed), your local CSVs, Kaggle CLI."""
    return data_sources()


@router.get("/decision")
def get_decision(
    underlying: str = "NIFTY",
    expiry: str | None = None,
    preset: str = "balanced",
    record: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Full pipeline → ranked strategies + the top pick sized and risk-checked.
    ``decision.action`` is ENTER / WAIT / NO_TRADE."""
    return run_decision(db, settings, underlying=underlying, expiry=expiry,
                        preset=preset, record=record)


@router.post("/decision")
def post_decision(
    underlying: str = Body("NIFTY", embed=True),
    expiry: str | None = Body(None, embed=True),
    preset: str = Body("balanced", embed=True),
    overrides: dict[str, Any] | None = Body(None, embed=True),
    compare_slugs: list[str] | None = Body(None, embed=True),
    record: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return run_decision(db, settings, underlying=underlying, expiry=expiry, preset=preset,
                        overrides=overrides, compare_slugs=compare_slugs, record=record)


@router.post("/backtest")
def post_backtest(
    underlying: str = Body("NIFTY", embed=True),
    start: str = Body(..., embed=True),
    end: str = Body(..., embed=True),
    mode: str = Body("simple", embed=True),
    preset: str = Body("balanced", embed=True),
    risk_level: str | None = Body(None, embed=True),
    capital: float | None = Body(None, embed=True),
    overrides: dict[str, Any] | None = Body(None, embed=True),
    expiry_kind: str = Body("weekly", embed=True),
    data_source: str = Body("synthetic", embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Walk-forward adaptive-options backtest. ``data_source='synthetic'``
    (default) exercises the decision mechanics only — results are flagged
    ``synthetic_data`` and are not evidence of an edge. ``'bhavcopy'`` /
    ``'auto'`` use real NSE EOD OI where the archive download succeeds;
    ``'local'`` / ``'local_bhavcopy'`` use CSVs under
    ``ADAPTIVE_OPTIONS_HISTORY_DIR`` (Kaggle / GitHub / self-exported)."""
    return backtest(
        db, settings, underlying=underlying, start=start, end=end, mode=mode,
        preset=preset, risk_level=risk_level, capital=capital, overrides=overrides,
        expiry_kind=expiry_kind, data_source=data_source,
    )


@router.post("/position/evaluate")
def post_position_evaluate(
    underlying: str = Body(..., embed=True),
    expiry: str = Body(..., embed=True),
    position: dict[str, Any] = Body(..., embed=True),
    current_pnl: float = Body(0.0, embed=True),
    preset: str = Body("balanced", embed=True),
    overrides: dict[str, Any] | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Phase 12 — run the leg-management engine against a live read for an
    open position. ``position`` matches leg_manager.OpenPosition fields."""
    return evaluate_open_position(
        db, settings, underlying=underlying, expiry=expiry, position=position,
        current_pnl=current_pnl, preset=preset, overrides=overrides,
    )


@router.post("/validation")
def post_validation(
    underlying: str = Body("NIFTY", embed=True),
    start: str = Body(..., embed=True),
    end: str = Body(..., embed=True),
    preset: str = Body("balanced", embed=True),
    overrides: dict[str, Any] | None = Body(None, embed=True),
    n_folds: int = Body(3, embed=True),
    mc_sims: int = Body(400, embed=True),
    sensitivity_params: list[str] | None = Body(None, embed=True),
    data_source: str = Body("synthetic", embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Phase 15 — walk-forward, Monte Carlo and parameter-sensitivity checks
    on a backtest config. Slow (runs many backtests); trigger deliberately."""
    return validate(
        db, settings, underlying=underlying, start=start, end=end, preset=preset,
        overrides=overrides, n_folds=n_folds, mc_sims=mc_sims,
        sensitivity_params=sensitivity_params, data_source=data_source,
    )


@router.post("/paper/runs", status_code=201)
def post_paper_run(
    underlying: str = Body("NIFTY", embed=True),
    preset: str = Body("balanced", embed=True),
    overrides: dict[str, Any] | None = Body(None, embed=True),
    capital: float | None = Body(None, embed=True),
    note: str | None = Body(None, embed=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _paper.start_run(db, underlying=underlying, preset=preset,
                            overrides=overrides, capital=capital, note=note)


@router.get("/paper/runs")
def get_paper_runs(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _paper.list_runs(db)


@router.get("/paper/runs/{run_id}")
def get_paper_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _paper.get_run(db, run_id)


@router.post("/paper/runs/{run_id}/tick")
def post_paper_tick(
    run_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _paper.tick_run(db, settings, run_id)


@router.post("/paper/runs/{run_id}/stop")
def post_paper_stop(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _paper.stop_run(db, run_id)


@router.get("/paper/runs/{run_id}/decisions")
def get_paper_decisions(
    run_id: str, limit: int = 200, db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _paper.run_decisions(db, run_id, limit=limit)


@router.post("/scheduler/tick")
def post_scheduler_tick(
    force: bool = True, db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Record a snapshot for the tracked underlyings and advance every ACTIVE
    paper run. The background worker calls this on its own loop during market
    hours; ``force=true`` runs it regardless."""
    return _scheduler.run_once(db, settings, force=force)

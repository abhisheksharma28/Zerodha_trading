import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.backtesting.robustness import monte_carlo
from app.backtesting.timeframes import catalog as timeframe_catalog
from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import NotFoundError
from app.models.backtest import Backtest
from app.schemas.backtest import (
    BacktestCreate,
    BacktestRead,
    BacktestReport,
    BacktestRunRequest,
)
from app.services import backtest_service

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("/timeframes")
def list_timeframes():
    """Every timeframe the backtest engine supports, for the UI selector."""
    return timeframe_catalog()


@router.get("", response_model=list[BacktestRead])
def list_backtests(db: Session = Depends(get_db)):
    return backtest_service.list_backtests(db)


@router.post("", response_model=BacktestRead, status_code=201)
def create_backtest(payload: BacktestCreate, db: Session = Depends(get_db)):
    """Creates the backtest row as PENDING. Actually running it requires
    historical candles (see app.market_data.cache.get_candles, which needs a
    connected broker session) and is triggered separately once that data
    pipeline is wired to a background worker — see app.services.backtest_service.
    run_backtest for the (already-implemented, unit-tested) execution path."""
    return backtest_service.create_backtest(db, payload)


@router.post("/{backtest_id}/run", response_model=BacktestRead)
def run_backtest(
    backtest_id: uuid.UUID,
    payload: BacktestRunRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Executes the backtest synchronously and returns the updated row.

    Candles come from ``payload.candles`` when supplied, otherwise from the
    connected broker session (paid Kite Connect plan only). Execution
    failures are reported as ``status == "failed"`` on the returned row, not
    as an HTTP error."""
    return backtest_service.execute_backtest(
        db,
        backtest_id,
        settings=settings,
        inline_candles=payload.candles if payload else None,
        cost_config=payload.costs if payload else None,
        parameter_overrides=payload.parameter_overrides if payload else None,
    )


@router.post("/{backtest_id}/robustness")
def backtest_monte_carlo(
    backtest_id: uuid.UUID, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Monte Carlo on this completed backtest's realised per-trade P&L —
    resample / reshuffle to see how much of the result is luck. Cheap; no
    re-run. Walk-forward + sensitivity live on the leaderboard, which owns a
    fixed canonical config."""
    bt = db.get(Backtest, backtest_id)
    if bt is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")
    trades = (bt.metrics or {}).get("trades") or []
    pnls = [float(t["net_pnl"]) for t in trades if t.get("net_pnl") is not None
            and not t.get("is_open")]
    return monte_carlo(pnls, initial_capital=float(bt.initial_capital))


@router.post("/{backtest_id}/param-sim")
def backtest_param_sim(
    backtest_id: uuid.UUID,
    pct: float = 5.0,
    n_samples: int = 24,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Re-run THIS backtest's exact config ~``n_samples`` times with every
    numeric strategy parameter jittered within +/- ``pct`` percent, and
    report the KPI distribution (Sharpe, return, max DD, ...). Slow; not
    cached — it is tied to one backtest row."""
    from app.backtesting.adhoc import fetch_candles
    from app.backtesting.costs import CostConfig, CostModel
    from app.backtesting.param_sim import run_param_sim
    from app.backtesting.timeframes import bars_per_year
    from app.models.strategy import StrategyVersion
    from app.strategies.registry import load_strategy_class

    bt = db.get(Backtest, backtest_id)
    if bt is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")
    version = db.get(StrategyVersion, bt.strategy_version_id)
    if version is None:
        raise NotFoundError("Strategy version not found")
    strategy_cls = load_strategy_class(version.source_code, version.entry_point)

    candles, skipped = fetch_candles(
        db, settings, symbols=list(bt.instrument_universe), timeframe=bt.timeframe,
        start=bt.start_date.date().isoformat(), end=bt.end_date.date().isoformat(),
    )
    if not candles:
        return {"available": False, "reason": "no price history for this backtest's window",
                "skipped": skipped}
    try:
        ppy = round(bars_per_year(bt.timeframe))
    except Exception:  # noqa: BLE001
        ppy = 252
    out = run_param_sim(
        strategy_cls, version.parameters, candles, initial_capital=float(bt.initial_capital),
        cost_model=CostModel(CostConfig()), pct=pct, n_samples=n_samples, periods_per_year=ppy,
    )
    out["skipped"] = skipped
    return out


@router.get("/{backtest_id}/report", response_model=BacktestReport)
def get_backtest_report(backtest_id: uuid.UUID, db: Session = Depends(get_db)):
    """Full report: expanded metrics, cost breakdown, equity/drawdown/monthly
    /daily-P&L/exposure series, trade distribution, and the trade list."""
    return backtest_service.backtest_report(db, backtest_id)


@router.get("/{backtest_id}", response_model=BacktestRead)
def get_backtest(backtest_id: uuid.UUID, db: Session = Depends(get_db)):
    return backtest_service.get_backtest(db, backtest_id)


@router.delete("/{backtest_id}", status_code=204)
def delete_backtest(backtest_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Delete a backtest and its persisted orders. 404 if it does not exist."""
    backtest_service.delete_backtest(db, backtest_id)
    return Response(status_code=204)

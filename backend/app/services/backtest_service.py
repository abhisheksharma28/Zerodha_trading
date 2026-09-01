"""Backtest creation + execution.

`run_backtest` executes synchronously in-process for now — for a
single-user local deployment this is fine for reasonably sized universes;
the natural follow-up is moving this onto app.workers so long backtests
don't block a request. It's structured as a plain function specifically so
that migration is a call-site change, not a rewrite.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.backtesting.engine import BacktestEngine
from app.backtesting.metrics import compute_metrics
from app.core.exceptions import NotFoundError, ValidationError
from app.models.backtest import Backtest
from app.models.enums import AuditAction, BacktestStatus, ChangeEntityType
from app.models.strategy import StrategyVersion
from app.repositories.backtest_repository import BacktestRepository
from app.schemas.backtest import BacktestCreate
from app.strategies.registry import load_strategy_class


def create_backtest(db: Session, payload: BacktestCreate) -> Backtest:
    version = db.get(StrategyVersion, payload.strategy_version_id)
    if version is None:
        raise NotFoundError(f"Strategy version {payload.strategy_version_id} not found")
    if payload.end_date <= payload.start_date:
        raise ValidationError("end_date must be after start_date")

    backtest = Backtest(
        strategy_version_id=payload.strategy_version_id,
        instrument_universe=payload.instrument_universe,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_capital=payload.initial_capital,
        timeframe=payload.timeframe,
        status=BacktestStatus.PENDING,
    )
    db.add(backtest)
    db.flush()

    record_audit(
        db,
        action=AuditAction.CREATE,
        entity_type=ChangeEntityType.STRATEGY_VERSION,
        entity_id=backtest.id,
        summary=f"Created backtest for strategy version {version.version_number}",
    )
    db.commit()
    db.refresh(backtest)
    return backtest


def run_backtest(
    db: Session,
    backtest_id,
    candles_by_instrument: dict[str, list],
) -> Backtest:
    """`candles_by_instrument` is pre-fetched by the caller (typically via
    app.market_data.cache.get_candles per instrument) so this function has
    no direct broker dependency and is easy to unit test with synthetic
    data — see backend/tests/test_backtesting.py."""

    backtest = db.get(Backtest, backtest_id)
    if backtest is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")

    version = db.get(StrategyVersion, backtest.strategy_version_id)
    if version is None:
        raise NotFoundError(f"Strategy version {backtest.strategy_version_id} not found")
    strategy_cls = load_strategy_class(version.source_code, version.entry_point)

    backtest.status = BacktestStatus.RUNNING
    backtest.started_at = datetime.now(UTC)
    db.commit()

    try:
        engine = BacktestEngine(strategy_cls, version.parameters, float(backtest.initial_capital))
        result = engine.run(candles_by_instrument)

        equity_curve = [[str(ts), value] for ts, value in result.equity_curve]
        metrics = compute_metrics([(str(ts), value) for ts, value in result.equity_curve])

        backtest.equity_curve = equity_curve
        backtest.metrics = metrics
        backtest.status = BacktestStatus.COMPLETED
        backtest.completed_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001
        backtest.status = BacktestStatus.FAILED
        backtest.error_message = str(exc)
        backtest.completed_at = datetime.now(UTC)
        db.commit()
        raise

    db.commit()
    db.refresh(backtest)
    return backtest


def get_backtest(db: Session, backtest_id) -> Backtest:
    backtest = BacktestRepository(db).get(backtest_id)
    if backtest is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")
    return backtest


def list_backtests(db: Session) -> list[Backtest]:
    return BacktestRepository(db).list()

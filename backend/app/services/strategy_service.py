"""Strategy + StrategyVersion business logic.

Key invariant enforced here (not just by convention): StrategyVersion rows
are immutable once created. "Editing" a strategy always means creating a new
StrategyVersion — there is no update_version method, deliberately, so that
anything referencing a version_id (a Backtest, a Deployment) can never have
the logic it ran change out from under it after the fact.
"""

from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.changelog.service import record_change
from app.core.exceptions import NotFoundError
from app.models.enums import AuditAction, ChangeEntityType
from app.models.strategy import Strategy, StrategyVersion
from app.repositories.strategy_repository import StrategyRepository, StrategyVersionRepository
from app.schemas.strategy import StrategyCreate, StrategyVersionCreate
from app.strategies.registry import load_strategy_class


def create_strategy(db: Session, payload: StrategyCreate) -> Strategy:
    # Validate the initial version compiles before persisting anything.
    load_strategy_class(payload.initial_version.source_code, payload.initial_version.entry_point)

    strategy = Strategy(name=payload.name, description=payload.description)
    db.add(strategy)
    db.flush()

    version = StrategyVersion(
        strategy_id=strategy.id,
        version_number=1,
        source_code=payload.initial_version.source_code,
        parameters=payload.initial_version.parameters,
        entry_point=payload.initial_version.entry_point,
        change_summary=payload.initial_version.change_summary or "Initial version",
    )
    db.add(version)
    db.flush()

    strategy.current_version_id = version.id

    record_audit(
        db,
        action=AuditAction.CREATE,
        entity_type=ChangeEntityType.STRATEGY,
        entity_id=strategy.id,
        summary=f"Created strategy '{strategy.name}' with initial version 1",
        after={"name": strategy.name, "version": 1},
    )

    db.commit()
    db.refresh(strategy)
    return strategy


def add_version(db: Session, strategy_id, payload: StrategyVersionCreate) -> StrategyVersion:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise NotFoundError(f"Strategy {strategy_id} not found")

    load_strategy_class(payload.source_code, payload.entry_point)

    version_repo = StrategyVersionRepository(db)
    next_number = version_repo.next_version_number(strategy_id)

    version = StrategyVersion(
        strategy_id=strategy_id,
        version_number=next_number,
        source_code=payload.source_code,
        parameters=payload.parameters,
        entry_point=payload.entry_point,
        change_summary=payload.change_summary,
    )
    db.add(version)
    db.flush()

    old_current = strategy.current_version_id
    strategy.current_version_id = version.id

    record_change(
        db,
        entity_type=ChangeEntityType.STRATEGY,
        entity_id=strategy.id,
        field="current_version_id",
        old_value=str(old_current) if old_current else None,
        new_value=str(version.id),
        reason=payload.change_summary,
    )
    record_audit(
        db,
        action=AuditAction.UPDATE,
        entity_type=ChangeEntityType.STRATEGY_VERSION,
        entity_id=version.id,
        summary=f"Added version {next_number} to strategy '{strategy.name}'",
    )

    db.commit()
    db.refresh(version)
    return version


def get_strategy(db: Session, strategy_id) -> Strategy:
    strategy = StrategyRepository(db).get(strategy_id)
    if strategy is None:
        raise NotFoundError(f"Strategy {strategy_id} not found")
    return strategy


def list_strategies(db: Session) -> list[Strategy]:
    return StrategyRepository(db).list()


def compare_versions(db: Session, version_a_id, version_b_id) -> dict:
    a = db.get(StrategyVersion, version_a_id)
    b = db.get(StrategyVersion, version_b_id)
    if a is None or b is None:
        raise NotFoundError("One or both strategy versions not found")

    all_keys = set(a.parameters.keys()) | set(b.parameters.keys())
    diff = {
        key: {"a": a.parameters.get(key), "b": b.parameters.get(key)}
        for key in all_keys
        if a.parameters.get(key) != b.parameters.get(key)
    }
    return {
        "a": a,
        "b": b,
        "parameter_diff": diff,
        "source_changed": a.source_code != b.source_code,
    }

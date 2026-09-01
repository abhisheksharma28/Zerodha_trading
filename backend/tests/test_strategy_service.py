import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError
from app.schemas.strategy import StrategyCreate, StrategyVersionCreate
from app.services import strategy_service


def _payload(name: str, source: str) -> StrategyCreate:
    return StrategyCreate(
        name=name,
        description="test",
        initial_version=StrategyVersionCreate(source_code=source, parameters={"x": 1}),
    )


def test_create_strategy_persists_initial_version(db, sample_strategy_source):
    strategy = strategy_service.create_strategy(db, _payload("Momentum v1", sample_strategy_source))

    assert strategy.current_version_id is not None
    assert len(strategy.versions) == 1
    assert strategy.versions[0].version_number == 1


def test_create_strategy_rejects_uncompilable_source(db):
    with pytest.raises(ValidationError):
        strategy_service.create_strategy(db, _payload("Broken", "this is not python("))


def test_create_strategy_rejects_missing_entry_point(db):
    with pytest.raises(ValidationError):
        strategy_service.create_strategy(
            db, _payload("NoEntryPoint", "class SomethingElse:\n    pass\n")
        )


def test_add_version_creates_new_immutable_row_and_updates_current(db, sample_strategy_source):
    strategy = strategy_service.create_strategy(db, _payload("Mean Reversion", sample_strategy_source))
    original_version_id = strategy.current_version_id

    v2 = strategy_service.add_version(
        db,
        strategy.id,
        StrategyVersionCreate(source_code=sample_strategy_source, parameters={"x": 2}, change_summary="tweak x"),
    )

    refreshed = strategy_service.get_strategy(db, strategy.id)
    assert v2.version_number == 2
    assert refreshed.current_version_id == v2.id
    assert refreshed.current_version_id != original_version_id
    # original version row is untouched
    original = [v for v in refreshed.versions if v.id == original_version_id][0]
    assert original.parameters == {"x": 1}


def test_compare_versions_reports_parameter_diff(db, sample_strategy_source):
    strategy = strategy_service.create_strategy(db, _payload("Compare Me", sample_strategy_source))
    v1_id = strategy.current_version_id
    v2 = strategy_service.add_version(
        db, strategy.id, StrategyVersionCreate(source_code=sample_strategy_source, parameters={"x": 99})
    )

    diff = strategy_service.compare_versions(db, v1_id, v2.id)

    assert diff["parameter_diff"] == {"x": {"a": 1, "b": 99}}
    assert diff["source_changed"] is False


def test_live_deployment_requires_exact_confirmation_phrase():
    import uuid

    from app.schemas.deployment import DeploymentCreate

    with pytest.raises(PydanticValidationError):
        DeploymentCreate(
            strategy_version_id=uuid.uuid4(),
            name="oops",
            mode="live",
            instrument_universe=["NSE:INFY"],
            live_trading_confirmation_phrase="yes please",
        )

    # Exact phrase succeeds.
    DeploymentCreate(
        strategy_version_id=uuid.uuid4(),
        name="ok",
        mode="live",
        instrument_universe=["NSE:INFY"],
        live_trading_confirmation_phrase="DEPLOY LIVE TRADING",
    )

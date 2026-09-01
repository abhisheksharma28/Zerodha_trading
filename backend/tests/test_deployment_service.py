import pytest

from app.core.exceptions import ConflictError
from app.models.enums import DeploymentStatus, TradingMode
from app.schemas.deployment import DeploymentCreate
from app.schemas.strategy import StrategyCreate, StrategyVersionCreate
from app.services import deployment_service, strategy_service


def _create_version(db, sample_strategy_source):
    strategy = strategy_service.create_strategy(
        db,
        StrategyCreate(
            name="Deployable Strategy",
            initial_version=StrategyVersionCreate(source_code=sample_strategy_source),
        ),
    )
    return strategy.current_version_id


def test_paper_deployment_does_not_require_confirmation(db, sample_strategy_source):
    version_id = _create_version(db, sample_strategy_source)
    deployment = deployment_service.create_deployment(
        db,
        DeploymentCreate(
            strategy_version_id=version_id,
            name="paper-1",
            mode=TradingMode.PAPER,
            instrument_universe=["NSE:INFY"],
        ),
    )
    assert deployment.live_trading_confirmed is False
    assert deployment.status == DeploymentStatus.PENDING


def test_live_deployment_records_confirmation_timestamp(db, sample_strategy_source):
    version_id = _create_version(db, sample_strategy_source)
    deployment = deployment_service.create_deployment(
        db,
        DeploymentCreate(
            strategy_version_id=version_id,
            name="live-1",
            mode=TradingMode.LIVE,
            instrument_universe=["NSE:INFY"],
            live_trading_confirmation_phrase="DEPLOY LIVE TRADING",
        ),
    )
    assert deployment.live_trading_confirmed is True
    assert deployment.live_trading_confirmed_at is not None


def test_full_lifecycle_transitions(db, sample_strategy_source):
    version_id = _create_version(db, sample_strategy_source)
    deployment = deployment_service.create_deployment(
        db,
        DeploymentCreate(
            strategy_version_id=version_id,
            name="lifecycle",
            mode=TradingMode.SIMULATION,
            instrument_universe=["NSE:INFY"],
        ),
    )

    running = deployment_service.deploy(db, deployment.id)
    assert running.status == DeploymentStatus.RUNNING

    paused = deployment_service.pause(db, deployment.id)
    assert paused.status == DeploymentStatus.PAUSED

    resumed = deployment_service.resume(db, deployment.id)
    assert resumed.status == DeploymentStatus.RUNNING

    stopped = deployment_service.stop(db, deployment.id)
    assert stopped.status == DeploymentStatus.STOPPED


def test_cannot_pause_a_deployment_that_never_ran(db, sample_strategy_source):
    version_id = _create_version(db, sample_strategy_source)
    deployment = deployment_service.create_deployment(
        db,
        DeploymentCreate(
            strategy_version_id=version_id,
            name="never-started",
            mode=TradingMode.SIMULATION,
            instrument_universe=["NSE:INFY"],
        ),
    )
    with pytest.raises(ConflictError):
        deployment_service.pause(db, deployment.id)


def test_clone_deployment_preserves_universe_and_links_source(db, sample_strategy_source):
    version_id = _create_version(db, sample_strategy_source)
    original = deployment_service.create_deployment(
        db,
        DeploymentCreate(
            strategy_version_id=version_id,
            name="original",
            mode=TradingMode.PAPER,
            instrument_universe=["NSE:INFY", "NSE:TCS"],
        ),
    )

    from app.schemas.deployment import DeploymentCloneRequest

    cloned = deployment_service.clone(
        db, original.id, DeploymentCloneRequest(name="clone-1", mode=TradingMode.PAPER)
    )

    assert cloned.instrument_universe == ["NSE:INFY", "NSE:TCS"]
    assert cloned.cloned_from_deployment_id == original.id

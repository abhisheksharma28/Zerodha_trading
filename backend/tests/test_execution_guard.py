"""Tests for the single most safety-critical module in the codebase — see
app/execution/guard.py's module docstring. These tests exist to make it
extremely hard to accidentally regress requirement #14 (no live order
without an explicit, current, database-verified LIVE deployment).
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.exceptions import UnsafeModeTransitionError
from app.execution import guard
from app.execution.router import OrderRouter
from app.models.deployment import Deployment
from app.models.enums import DeploymentStatus, TradingMode
from app.models.strategy import Strategy, StrategyVersion


def _make_strategy_version(db) -> StrategyVersion:
    strategy = Strategy(name=f"s-{uuid.uuid4()}")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version_number=1,
        source_code="from app.strategies.base import BaseStrategy\nclass Strategy(BaseStrategy):\n    def on_bar(self, bar): pass\n",
        parameters={},
    )
    db.add(version)
    db.flush()
    return version


def _make_deployment(db, version, **overrides) -> Deployment:
    defaults = {
        "strategy_version_id": version.id,
        "name": "test-deployment",
        "mode": TradingMode.LIVE,
        "status": DeploymentStatus.RUNNING,
        "instrument_universe": ["NSE:INFY"],
        "config": {},
        "live_trading_confirmed": True,
        "live_trading_confirmed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    deployment = Deployment(**defaults)
    db.add(deployment)
    db.flush()
    return deployment


def test_fully_valid_live_deployment_is_authorized(db):
    version = _make_strategy_version(db)
    deployment = _make_deployment(db, version)

    result = guard.assert_live_trading_authorized(db, str(deployment.id))

    assert result.id == deployment.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": TradingMode.PAPER},
        {"mode": TradingMode.SIMULATION},
        {"status": DeploymentStatus.PENDING},
        {"status": DeploymentStatus.PAUSED},
        {"status": DeploymentStatus.STOPPED},
        {"live_trading_confirmed": False, "live_trading_confirmed_at": None},
    ],
)
def test_anything_less_than_fully_confirmed_live_running_is_rejected(db, overrides):
    version = _make_strategy_version(db)
    deployment = _make_deployment(db, version, **overrides)

    with pytest.raises(UnsafeModeTransitionError):
        guard.assert_live_trading_authorized(db, str(deployment.id))


def test_nonexistent_deployment_is_rejected(db):
    with pytest.raises(UnsafeModeTransitionError):
        guard.assert_live_trading_authorized(db, str(uuid.uuid4()))


def test_order_router_refuses_live_mode_without_broker_client(db):
    version = _make_strategy_version(db)
    deployment = _make_deployment(db, version, mode=TradingMode.LIVE)

    with pytest.raises(RuntimeError):
        OrderRouter(db, deployment, broker_client=None)


def test_order_router_refuses_broker_client_for_non_live_mode(db):
    version = _make_strategy_version(db)
    deployment = _make_deployment(
        db, version, mode=TradingMode.PAPER, live_trading_confirmed=False,
        live_trading_confirmed_at=None,
    )

    class _FakeBrokerClient:
        pass

    with pytest.raises(RuntimeError):
        OrderRouter(db, deployment, broker_client=_FakeBrokerClient())


def test_paper_and_simulation_orders_never_touch_a_broker_client(db):
    """Structural guarantee: PaperExecutor/SimulationExecutor don't even
    accept a broker_client argument, so this test also acts as a compile-time
    check via inspection that no such parameter was added."""
    import inspect

    from app.execution.paper_executor import PaperExecutor
    from app.execution.sim_executor import SimulationExecutor

    for cls in (PaperExecutor, SimulationExecutor):
        params = inspect.signature(cls.__init__).parameters
        assert "broker_client" not in params, (
            f"{cls.__name__} must never accept a broker_client — paper/"
            "simulation modes must be structurally incapable of live order "
            "placement."
        )

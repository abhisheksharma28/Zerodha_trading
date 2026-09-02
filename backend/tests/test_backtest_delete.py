"""Deleting a backtest row (and its cascade of persisted orders)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.backtest import BacktestCreate
from app.schemas.strategy import StrategyCreate, StrategyVersionCreate
from app.services import backtest_service, strategy_service


def _make_backtest(db, src):
    strategy = strategy_service.create_strategy(
        db,
        StrategyCreate(
            name="BT delete", initial_version=StrategyVersionCreate(source_code=src)
        ),
    )
    return backtest_service.create_backtest(
        db,
        BacktestCreate(
            strategy_version_id=strategy.current_version_id,
            instrument_universe=["NSE:INFY"],
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 6, 1),
            initial_capital=100_000.0,
            timeframe="1d",
        ),
    )


def test_delete_backtest_removes_the_row(db, sample_strategy_source):
    bt = _make_backtest(db, sample_strategy_source)
    bid = bt.id
    assert any(b.id == bid for b in backtest_service.list_backtests(db))

    backtest_service.delete_backtest(db, bid)

    assert not any(b.id == bid for b in backtest_service.list_backtests(db))
    with pytest.raises(NotFoundError):
        backtest_service.get_backtest(db, bid)


def test_delete_unknown_backtest_raises_not_found(db):
    with pytest.raises(NotFoundError):
        backtest_service.delete_backtest(db, uuid.uuid4())

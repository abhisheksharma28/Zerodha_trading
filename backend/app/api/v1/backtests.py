import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.backtest import BacktestCreate, BacktestRead
from app.services import backtest_service

router = APIRouter(prefix="/backtests", tags=["backtests"])


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


@router.get("/{backtest_id}", response_model=BacktestRead)
def get_backtest(backtest_id: uuid.UUID, db: Session = Depends(get_db)):
    return backtest_service.get_backtest(db, backtest_id)

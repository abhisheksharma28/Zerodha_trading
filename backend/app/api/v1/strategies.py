import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.strategy import (
    StrategyCreate,
    StrategyDetail,
    StrategyRead,
    StrategyVersionCompare,
    StrategyVersionCreate,
    StrategyVersionRead,
)
from app.services import strategy_service

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyRead])
def list_strategies(db: Session = Depends(get_db)):
    return strategy_service.list_strategies(db)


@router.post("", response_model=StrategyRead, status_code=201)
def create_strategy(payload: StrategyCreate, db: Session = Depends(get_db)):
    return strategy_service.create_strategy(db, payload)


@router.get("/{strategy_id}", response_model=StrategyDetail)
def get_strategy(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    return strategy_service.get_strategy(db, strategy_id)


@router.post("/{strategy_id}/versions", response_model=StrategyVersionRead, status_code=201)
def add_version(strategy_id: uuid.UUID, payload: StrategyVersionCreate, db: Session = Depends(get_db)):
    return strategy_service.add_version(db, strategy_id, payload)


@router.get("/versions/compare", response_model=StrategyVersionCompare)
def compare_versions(a: uuid.UUID, b: uuid.UUID, db: Session = Depends(get_db)):
    return strategy_service.compare_versions(db, a, b)

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderRead

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/by-deployment/{deployment_id}", response_model=list[OrderRead])
def list_for_deployment(deployment_id: uuid.UUID, db: Session = Depends(get_db)):
    return OrderRepository(db).list_for_deployment(deployment_id)


@router.get("/by-backtest/{backtest_id}", response_model=list[OrderRead])
def list_for_backtest(backtest_id: uuid.UUID, db: Session = Depends(get_db)):
    return OrderRepository(db).list_for_backtest(backtest_id)

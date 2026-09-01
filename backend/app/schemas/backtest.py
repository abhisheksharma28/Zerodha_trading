import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import BacktestStatus


class BacktestCreate(BaseModel):
    strategy_version_id: uuid.UUID
    instrument_universe: list[str]
    start_date: datetime
    end_date: datetime
    initial_capital: float
    timeframe: str = "day"


class BacktestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_version_id: uuid.UUID
    status: BacktestStatus
    instrument_universe: list
    start_date: datetime
    end_date: datetime
    initial_capital: float
    timeframe: str
    metrics: dict | None
    equity_curve: list | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import StrategyStatus


class StrategyVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    version_number: int
    source_code: str
    parameters: dict
    entry_point: str
    change_summary: str | None
    cloned_from_version_id: uuid.UUID | None
    created_at: datetime


class StrategyVersionCreate(BaseModel):
    source_code: str = Field(..., min_length=1)
    parameters: dict = Field(default_factory=dict)
    entry_point: str = "Strategy"
    change_summary: str | None = None


class StrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: StrategyStatus
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    initial_version: StrategyVersionCreate


class StrategyDetail(StrategyRead):
    versions: list[StrategyVersionRead] = []


class StrategyVersionCompare(BaseModel):
    a: StrategyVersionRead
    b: StrategyVersionRead
    parameter_diff: dict
    source_changed: bool

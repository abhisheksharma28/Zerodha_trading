import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AuditAction, ChangeEntityType, TradingMode


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor: str
    action: AuditAction
    entity_type: ChangeEntityType
    entity_id: uuid.UUID | None
    mode: TradingMode | None
    summary: str
    before: dict | None
    after: dict | None


class ChangeLogEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    entity_type: ChangeEntityType
    entity_id: uuid.UUID
    field: str
    old_value: dict | None
    new_value: dict | None
    changed_by: str
    reason: str | None

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.enums import ChangeEntityType
from app.repositories.audit_repository import AuditLogRepository, ChangeLogRepository
from app.schemas.audit import AuditLogRead, ChangeLogEntryRead

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    limit: int = Query(100, le=1000), offset: int = 0, db: Session = Depends(get_db)
):
    return AuditLogRepository(db).list(limit=limit, offset=offset)


@router.get("/change-log", response_model=list[ChangeLogEntryRead])
def list_change_log(
    entity_type: ChangeEntityType, entity_id: uuid.UUID, db: Session = Depends(get_db)
):
    return ChangeLogRepository(db).list_for_entity(entity_type, entity_id)

from sqlalchemy import select

from app.models.audit import AuditLog, ChangeLogEntry
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog


class ChangeLogRepository(BaseRepository[ChangeLogEntry]):
    model = ChangeLogEntry

    def list_for_entity(self, entity_type, entity_id, *, limit: int = 200) -> list[ChangeLogEntry]:
        stmt = (
            select(ChangeLogEntry)
            .where(
                ChangeLogEntry.entity_type == entity_type,
                ChangeLogEntry.entity_id == entity_id,
            )
            .order_by(ChangeLogEntry.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

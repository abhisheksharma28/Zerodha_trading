import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import AuditAction, ChangeEntityType, TradingMode


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """Append-only record of "what happened and why" — every state-changing
    action in the system, especially anything touching order placement or
    mode transitions. This table is never updated or deleted from
    application code (no repository method exists for either); enforce that
    at the DB user/grant level in production too.
    """

    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="user")
    action: Mapped[AuditAction] = mapped_column(nullable=False)
    entity_type: Mapped[ChangeEntityType] = mapped_column(nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    mode: Mapped[TradingMode | None] = mapped_column(nullable=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_metadata: Mapped[dict | None] = mapped_column(JSONB)  # ip, user-agent, etc.


class ChangeLogEntry(Base, UUIDPrimaryKeyMixin):
    """Immutable, field-level change log (requirement #10) — distinct from
    AuditLog: AuditLog answers "what action happened", ChangeLogEntry answers
    "what was this field before vs after", which is what version/config diff
    views (requirement #11) render directly.
    """

    __tablename__ = "change_log_entries"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    entity_type: Mapped[ChangeEntityType] = mapped_column(nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(200), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    changed_by: Mapped[str] = mapped_column(String(100), nullable=False, default="user")
    reason: Mapped[str | None] = mapped_column(String(1000))

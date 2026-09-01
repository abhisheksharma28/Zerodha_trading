"""Append-only audit logging.

Call `record` from every service-layer mutation (strategy create/update,
deployment create/deploy/pause/resume/stop/clone, broker connect/disconnect,
order placement/rejection, risk breaches). There is deliberately no
update/delete function in this module — audit rows are write-once.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.execution.guard import now_utc
from app.models.audit import AuditLog
from app.models.enums import AuditAction, ChangeEntityType, TradingMode


def record(
    db: Session,
    *,
    action: AuditAction,
    entity_type: ChangeEntityType,
    entity_id: Any = None,
    summary: str,
    mode: TradingMode | None = None,
    before: dict | None = None,
    after: dict | None = None,
    actor: str = "user",
    request_metadata: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        created_at=now_utc(),
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        mode=mode,
        summary=summary,
        before=before,
        after=after,
        request_metadata=request_metadata,
    )
    db.add(row)
    db.flush()
    return row

"""Immutable, field-level change log — see app.models.audit.ChangeLogEntry
for how this differs from the audit log. Call `record_change` (or
`record_changes` for a dict diff) from any service method that mutates a
tracked entity's fields.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.execution.guard import now_utc
from app.models.audit import ChangeLogEntry
from app.models.enums import ChangeEntityType


def record_change(
    db: Session,
    *,
    entity_type: ChangeEntityType,
    entity_id: Any,
    field: str,
    old_value: Any,
    new_value: Any,
    changed_by: str = "user",
    reason: str | None = None,
) -> ChangeLogEntry:
    row = ChangeLogEntry(
        created_at=now_utc(),
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        old_value={"value": old_value} if old_value is not None else None,
        new_value={"value": new_value} if new_value is not None else None,
        changed_by=changed_by,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def record_changes(
    db: Session,
    *,
    entity_type: ChangeEntityType,
    entity_id: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    changed_by: str = "user",
    reason: str | None = None,
) -> list[ChangeLogEntry]:
    rows = []
    for field, new_value in after.items():
        old_value = before.get(field)
        if old_value != new_value:
            rows.append(
                record_change(
                    db,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field=field,
                    old_value=old_value,
                    new_value=new_value,
                    changed_by=changed_by,
                    reason=reason,
                )
            )
    return rows

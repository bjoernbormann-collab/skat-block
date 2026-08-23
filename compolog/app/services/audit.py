"""Change history recording (Modul 1).

Used by every write path that touches data a tax auditor or a confused future you
might ask about. Writes one row per changed field.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.enums import AuditAction

# Fields never worth recording (they change on every write anyway).
IGNORED_FIELDS = {"updated_at", "created_at", "updated_by_id"}


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def record_changes(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
    user_id: int | None = None,
    source: str = "web",
) -> int:
    """Diff two field dicts and log every difference. Returns the row count."""
    written = 0
    for field, new_value in after.items():
        if field in IGNORED_FIELDS:
            continue
        old_value = before.get(field)
        if old_value == new_value:
            continue
        db.add(
            AuditLog(
                entity_type=entity_type,
                entity_id=entity_id,
                action=AuditAction.UPDATE.value,
                field_name=field,
                old_value=_stringify(old_value),
                new_value=_stringify(new_value),
                user_id=user_id,
                source=source,
            )
        )
        written += 1
    return written


def record_event(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: AuditAction,
    user_id: int | None = None,
    source: str = "web",
    note: str | None = None,
) -> None:
    """Log a creation or deletion (no field-level diff)."""
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action.value,
            field_name=None,
            old_value=None,
            new_value=note,
            user_id=user_id,
            source=source,
        )
    )


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    """Read the given attributes off an ORM object into a plain dict.

    Take one before the change and one after, then hand both to record_changes.
    """
    return {field: getattr(obj, field, None) for field in fields}

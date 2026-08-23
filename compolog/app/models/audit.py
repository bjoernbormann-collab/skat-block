"""Change history (Modul 1: 'wer hat wann welches Feld geaendert').

One row per changed field, not per changed record. That is chattier but makes the
'welches Feld von welchem auf welchen Wert' question answerable with a plain
SELECT instead of a JSON diff at read time.

Deliberately append-only: there is no update or delete path in the service layer.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)   # e.g. "article"
    entity_id: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)        # AuditAction
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Free-text origin for machine-made changes: "ebay-sync", "xlsx-import", "web".
    source: Mapped[str] = mapped_column(String(32), default="web", nullable=False)

    user: Mapped[User | None] = relationship()

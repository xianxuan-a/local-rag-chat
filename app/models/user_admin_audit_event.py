"""Immutable audit records for administrator-managed user changes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class UserAdminAuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_admin_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('USER_UPDATED')",
            name="ck_user_admin_audit_events_action",
        ),
        Index(
            "ix_user_admin_audit_events_target_created",
            "target_user_id",
            "created_at",
        ),
        Index(
            "ix_user_admin_audit_events_actor_created",
            "actor_user_id",
            "created_at",
        ),
    )

    actor_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )

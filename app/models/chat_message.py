"""Chat-message database model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    JSON,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now
from app.core.retrieval_modes import WebSearchStatus

if TYPE_CHECKING:
    from app.models.chat_session import ChatSession
    from app.models.message_feedback import MessageFeedback


class MessageRole(str, Enum):
    """Supported chat participant roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """Persisted lifecycle for one chat message."""

    COMPLETE = "complete"
    STREAMING = "streaming"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChatMessage(UUIDPrimaryKeyMixin, Base):
    """One user, assistant, or system message in a chat session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('complete', 'streaming', 'failed', 'cancelled')",
            name="ck_chat_messages_status",
        ),
        UniqueConstraint(
            "reply_to_message_id",
            name="uq_chat_messages_reply_to_message_id",
        ),
        Index(
            "ix_chat_messages_session_created",
            "session_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_chat_messages_session_status",
            "session_id",
            "status",
        ),
        Index(
            "ix_chat_messages_role_status_created",
            "role",
            "status",
            "created_at",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        SqlEnum(
            MessageRole,
            name="message_role_enum",
            native_enum=False,
            values_callable=lambda enum_class: [item.value for item in enum_class],
            validate_strings=True,
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[MessageStatus] = mapped_column(
        SqlEnum(
            MessageStatus,
            name="message_status_enum",
            native_enum=False,
            length=16,
            values_callable=lambda enum_class: [item.value for item in enum_class],
            validate_strings=True,
        ),
        default=MessageStatus.COMPLETE,
        server_default=MessageStatus.COMPLETE.value,
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    effective_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    web_search_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    web_search_status: Mapped[str] = mapped_column(
        String(32),
        default=WebSearchStatus.NOT_REQUESTED.value,
        server_default=WebSearchStatus.NOT_REQUESTED.value,
        nullable=False,
    )
    web_trigger_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    knowledge_source_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    web_source_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    fallback_reason: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    reply_to_message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
    reply_to: Mapped["ChatMessage | None"] = relationship(
        remote_side="ChatMessage.id",
        foreign_keys=[reply_to_message_id],
    )
    feedback: Mapped["MessageFeedback | None"] = relationship(
        back_populates="message",
        uselist=False,
        passive_deletes=True,
    )

    @property
    def feedback_value(self) -> str | None:
        return None if self.feedback is None else self.feedback.value

    def __repr__(self) -> str:
        role = self.role.value if isinstance(self.role, MessageRole) else self.role
        return f"ChatMessage(id={self.id!r}, role={role!r})"

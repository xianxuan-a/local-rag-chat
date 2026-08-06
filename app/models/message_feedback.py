"""Persistent like/dislike feedback for assistant messages."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.user import User


class FeedbackValue(str, Enum):
    LIKE = "like"
    DISLIKE = "dislike"


class MessageFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "message_feedbacks"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_message_feedbacks_message_id"),
        CheckConstraint(
            "value IN ('like', 'dislike')",
            name="ck_message_feedbacks_value",
        ),
    )

    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    message: Mapped["ChatMessage"] = relationship(back_populates="feedback")
    updated_by: Mapped["User | None"] = relationship()

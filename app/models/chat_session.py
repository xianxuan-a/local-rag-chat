"""Chat-session database model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.knowledge_base import KnowledgeBase


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A conversation associated with exactly one knowledge base."""

    __tablename__ = "chat_sessions"

    knowledge_base_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        back_populates="sessions"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"ChatSession(id={self.id!r}, title={self.title!r})"

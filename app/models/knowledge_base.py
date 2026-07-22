"""Knowledge-base database model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.chat_session import ChatSession
    from app.models.file_record import FileRecord


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A logical collection of uploaded source files and chat sessions."""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    files: Mapped[list["FileRecord"]] = relationship(
        back_populates="knowledge_base",
        passive_deletes=True,
    )
    sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="knowledge_base",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"KnowledgeBase(id={self.id!r}, name={self.name!r})"

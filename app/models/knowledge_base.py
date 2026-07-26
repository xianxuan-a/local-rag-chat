"""Knowledge-base database model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SqlEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.chat_session import ChatSession
    from app.models.file_record import FileRecord


class RebuildStatus(str, Enum):
    """Persistent state for one knowledge-base rebuild."""

    IDLE = "IDLE"
    BUILDING = "BUILDING"
    FAILED = "FAILED"


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A logical collection of uploaded source files and chat sessions."""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_collection_name: Mapped[str | None] = mapped_column(
        String(63), nullable=True
    )
    active_embedding_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    previous_collection_name: Mapped[str | None] = mapped_column(
        String(63), nullable=True
    )
    previous_embedding_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    building_collection_name: Mapped[str | None] = mapped_column(
        String(63), nullable=True
    )
    building_embedding_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    cleanup_collection_name: Mapped[str | None] = mapped_column(
        String(63), nullable=True
    )
    rebuild_status: Mapped[RebuildStatus] = mapped_column(
        SqlEnum(
            RebuildStatus,
            name="rebuild_status_enum",
            native_enum=False,
            values_callable=lambda enum_class: [item.value for item in enum_class],
            validate_strings=True,
        ),
        default=RebuildStatus.IDLE,
        server_default=RebuildStatus.IDLE.value,
        nullable=False,
    )
    rebuild_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    building_started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )

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

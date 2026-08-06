"""Knowledge-base database model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Enum as SqlEnum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.core.retrieval_modes import KnowledgeBaseWebPolicy

if TYPE_CHECKING:
    from app.models.chat_session import ChatSession
    from app.models.file_record import FileRecord
    from app.models.user import User


class RebuildStatus(str, Enum):
    """Persistent state for one knowledge-base rebuild."""

    IDLE = "IDLE"
    BUILDING = "BUILDING"
    FAILED = "FAILED"


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A logical collection of uploaded source files and chat sessions."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "name", name="uq_knowledge_bases_owner_id_name"
        ),
        Index(
            "ix_knowledge_bases_owner_updated",
            "owner_id",
            "updated_at",
            "id",
        ),
    )

    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    web_access_policy: Mapped[str] = mapped_column(
        String(16),
        default=KnowledgeBaseWebPolicy.INHERIT.value,
        server_default=KnowledgeBaseWebPolicy.INHERIT.value,
        nullable=False,
    )
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
    rebuild_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
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
    owner: Mapped["User"] = relationship(back_populates="knowledge_bases")

    def __repr__(self) -> str:
        return f"KnowledgeBase(id={self.id!r}, name={self.name!r})"

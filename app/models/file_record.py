"""Uploaded-file metadata model."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from datetime import datetime

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase


class FileStatus(str, Enum):
    """Lifecycle state of a source file after it has been accepted."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class FileRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persistent metadata for one safely stored upload."""

    __tablename__ = "file_records"
    __table_args__ = (
        CheckConstraint("file_size > 0", name="ck_file_records_file_size"),
        CheckConstraint("chunk_count >= 0", name="ck_file_records_chunk_count"),
    )

    knowledge_base_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[FileStatus] = mapped_column(
        SqlEnum(
            FileStatus,
            name="file_status_enum",
            native_enum=False,
            values_callable=lambda enum_class: [item.value for item in enum_class],
            validate_strings=True,
        ),
        default=FileStatus.PENDING,
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_active_vectors: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    active_index_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_successful_indexed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="files")

    def __repr__(self) -> str:
        status = self.status.value if isinstance(self.status, FileStatus) else self.status
        return (
            f"FileRecord(id={self.id!r}, original_name={self.original_name!r}, "
            f"status={status!r})"
        )

"""Reusable, owner-scoped RAG evaluation dataset metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.user import User


class EvaluationDataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "name",
            name="uq_evaluation_datasets_owner_id_name",
        ),
        Index(
            "ix_evaluation_datasets_owner_created",
            "owner_id",
            "created_at",
            "id",
        ),
    )

    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="evaluation_datasets")
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="evaluation_dataset",
        passive_deletes=True,
    )

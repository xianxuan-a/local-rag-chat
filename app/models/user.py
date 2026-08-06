"""Authenticated application user."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evaluation_dataset import EvaluationDataset
    from app.models.job import Job
    from app.models.knowledge_base import KnowledgeBase


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    USER = "USER"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "username_normalized", name="uq_users_username_normalized"
        ),
        UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        CheckConstraint("role IN ('ADMIN', 'USER')", name="ck_users_user_role"),
    )

    username: Mapped[str] = mapped_column(String(100), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(640), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), default=UserRole.USER.value, server_default="USER", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="0", nullable=False
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="1", nullable=False
    )

    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        back_populates="owner", passive_deletes=True
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="created_by",
        foreign_keys="Job.created_by_id",
        passive_deletes=True,
    )
    evaluation_datasets: Mapped[list["EvaluationDataset"]] = relationship(
        back_populates="owner",
        passive_deletes=True,
    )

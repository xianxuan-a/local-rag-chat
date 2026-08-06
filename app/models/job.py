"""Durable background job and runtime maintenance state models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evaluation_dataset import EvaluationDataset
    from app.models.user import User


class JobType(str, Enum):
    FILE_PROCESS = "FILE_PROCESS"
    KB_REBUILD = "KB_REBUILD"
    KB_CLEANUP_RETIRED = "KB_CLEANUP_RETIRED"
    RAG_EVALUATION = "RAG_EVALUATION"
    BACKUP = "BACKUP"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


NON_TERMINAL_JOB_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
    JobStatus.CANCEL_REQUESTED.value,
)
TERMINAL_JOB_STATUSES = (
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','CANCEL_REQUESTED',"
            "'SUCCEEDED','FAILED','CANCELLED')",
            name="ck_jobs_job_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_jobs_job_progress"
        ),
        CheckConstraint(
            "attempt >= 0 AND max_attempts >= 1", name="ck_jobs_job_attempts"
        ),
        CheckConstraint(
            "evaluation_mode IS NULL OR evaluation_mode IN ('retrieval','rag')",
            name="ck_jobs_evaluation_mode",
        ),
        Index(
            "ix_jobs_claim",
            "status",
            "run_after",
            "lease_expires_at",
            "created_at",
        ),
        Index(
            "ix_jobs_resource", "resource_type", "resource_id", "status"
        ),
        Index(
            "ix_jobs_collection_pin",
            "job_type",
            "status",
            "collection_name",
        ),
        Index(
            "ix_jobs_evaluation_dataset",
            "evaluation_dataset_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_jobs_type_created",
            "job_type",
            "created_at",
            "id",
        ),
        Index(
            "ix_jobs_creator_type_created",
            "created_by_id",
            "job_type",
            "created_at",
            "id",
        ),
    )

    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=JobStatus.QUEUED.value, server_default="QUEUED"
    )
    created_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resource_name_snapshot: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    retry_of_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    collection_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    embedding_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    dataset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    evaluation_dataset_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evaluation_datasets.id", ondelete="SET NULL"),
        nullable=True,
    )
    evaluation_mode: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    evaluation_run_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    budget_total_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_reserved_calls: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    budget_used_calls: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    budget_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_reserved_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    budget_used_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_by: Mapped["User | None"] = relationship(
        back_populates="jobs", foreign_keys=[created_by_id]
    )
    retry_of: Mapped["Job | None"] = relationship(
        remote_side="Job.id", foreign_keys=[retry_of_job_id]
    )
    evaluation_dataset: Mapped["EvaluationDataset | None"] = relationship(
        back_populates="jobs",
        foreign_keys=[evaluation_dataset_id],
    )


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    owner_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

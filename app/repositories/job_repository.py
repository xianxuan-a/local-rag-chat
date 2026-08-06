"""Short-transaction durable job queue operations for SQLite."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import (
    FileRecord,
    Job,
    JobStatus,
    JobType,
    NON_TERMINAL_JOB_STATUSES,
)


class JobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, job: Job) -> Job:
        self.db.add(job)
        self.db.flush()
        self.db.refresh(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.db.get(Job, str(job_id))

    def list_for_user(self, user_id: str, *, is_admin: bool) -> list[Job]:
        statement = select(Job)
        if not is_admin:
            statement = statement.where(Job.created_by_id == user_id)
        return list(
            self.db.scalars(
                statement.order_by(Job.created_at.desc(), Job.id.desc())
            ).all()
        )

    def latest_for_resource(
        self,
        *,
        job_type: JobType,
        resource_type: str,
        resource_id: str,
    ) -> Job | None:
        return self.db.scalar(
            select(Job)
            .where(
                Job.job_type == job_type.value,
                Job.resource_type == resource_type,
                Job.resource_id == str(resource_id),
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )

    def claim_next(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> Job | None:
        candidate = (
            select(Job.id)
            .where(
                Job.status == JobStatus.QUEUED.value,
                Job.run_after <= now,
            )
            .order_by(Job.run_after.asc(), Job.created_at.asc(), Job.id.asc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(Job)
            .where(
                Job.id == candidate,
                Job.status == JobStatus.QUEUED.value,
                Job.run_after <= now,
            )
            .values(
                status=JobStatus.RUNNING.value,
                lease_owner=lease_owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                last_heartbeat_at=now,
                started_at=func.coalesce(Job.started_at, now),
                attempt=Job.attempt + 1,
                stage="CLAIMED",
            )
            .returning(Job)
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def heartbeat(
        self,
        *,
        job_id: str,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
        progress: int | None = None,
        stage: str | None = None,
    ) -> bool:
        values: dict[str, object] = {
            "last_heartbeat_at": now,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
        }
        if progress is not None:
            values["progress"] = progress
        if stage is not None:
            values["stage"] = stage
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.lease_owner == lease_owner,
                Job.status.in_(
                    (
                        JobStatus.RUNNING.value,
                        JobStatus.CANCEL_REQUESTED.value,
                    )
                ),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount == 1

    def finish(
        self,
        *,
        job_id: str,
        lease_owner: str,
        status: JobStatus,
        now: datetime,
        result: dict[str, object] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.lease_owner == lease_owner,
                Job.status.in_(
                    (
                        JobStatus.RUNNING.value,
                        JobStatus.CANCEL_REQUESTED.value,
                    )
                ),
            )
            .values(
                status=status.value,
                result=result,
                progress=100 if status is JobStatus.SUCCEEDED else Job.progress,
                stage=status.value,
                error_code=error_code,
                error_message=error_message,
                lease_owner=None,
                lease_expires_at=None,
                last_heartbeat_at=None,
                finished_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount == 1

    def request_cancel(self, job_id: str, now: datetime) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        if job.status == JobStatus.QUEUED.value:
            job.status = JobStatus.CANCELLED.value
            job.cancel_requested_at = now
            job.finished_at = now
            job.stage = "CANCELLED_BEFORE_START"
        elif job.status == JobStatus.RUNNING.value:
            job.status = JobStatus.CANCEL_REQUESTED.value
            job.cancel_requested_at = now
        self.db.flush()
        return job

    def expired(self, now: datetime) -> list[Job]:
        return list(
            self.db.scalars(
                select(Job)
                .where(
                    Job.status.in_(
                        (
                            JobStatus.RUNNING.value,
                            JobStatus.CANCEL_REQUESTED.value,
                        )
                    ),
                    Job.lease_expires_at.is_not(None),
                    Job.lease_expires_at < now,
                )
                .order_by(Job.lease_expires_at.asc(), Job.id.asc())
            ).all()
        )

    def has_nonterminal(
        self,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        exclude_job_id: str | None = None,
    ) -> bool:
        conditions = [Job.status.in_(NON_TERMINAL_JOB_STATUSES)]
        if resource_type is not None:
            conditions.append(Job.resource_type == resource_type)
        if resource_id is not None:
            conditions.append(Job.resource_id == resource_id)
        if exclude_job_id is not None:
            conditions.append(Job.id != exclude_job_id)
        return bool(self.db.scalar(select(exists().where(*conditions))))

    def collection_is_pinned(
        self, collection_name: str, *, exclude_job_id: str | None = None
    ) -> bool:
        conditions = [
            Job.job_type == JobType.RAG_EVALUATION.value,
            Job.status.in_(NON_TERMINAL_JOB_STATUSES),
            Job.collection_name == collection_name,
        ]
        if exclude_job_id:
            conditions.append(Job.id != exclude_job_id)
        return bool(self.db.scalar(select(exists().where(*conditions))))

    def collection_is_referenced_by_nonterminal_job(
        self,
        collection_name: str,
        *,
        exclude_job_id: str | None = None,
    ) -> bool:
        conditions = [
            Job.status.in_(NON_TERMINAL_JOB_STATUSES),
            Job.collection_name == collection_name,
        ]
        if exclude_job_id:
            conditions.append(Job.id != exclude_job_id)
        return bool(self.db.scalar(select(exists().where(*conditions))))

    def has_nonterminal_knowledge_base_job(
        self,
        knowledge_base_id: str,
        *,
        job_types: tuple[JobType, ...] | None = None,
        exclude_evaluations: bool = True,
    ) -> bool:
        conditions = [
            Job.resource_type == "KNOWLEDGE_BASE",
            Job.resource_id == str(knowledge_base_id),
            Job.status.in_(NON_TERMINAL_JOB_STATUSES),
        ]
        if job_types is not None:
            conditions.append(
                Job.job_type.in_(tuple(item.value for item in job_types))
            )
        elif exclude_evaluations:
            conditions.append(Job.job_type != JobType.RAG_EVALUATION.value)
        return bool(self.db.scalar(select(exists().where(*conditions))))

    def has_nonterminal_file_job_for_knowledge_base(
        self, knowledge_base_id: str
    ) -> bool:
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        Job.resource_type == "FILE",
                        Job.status.in_(NON_TERMINAL_JOB_STATUSES),
                        Job.resource_id.in_(
                            select(FileRecord.id).where(
                                FileRecord.knowledge_base_id
                                == str(knowledge_base_id)
                            )
                        ),
                    )
                )
            )
        )

    def reserve_evaluation_budget(
        self,
        *,
        job_id: str,
        calls: int,
        tokens: int,
    ) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_(
                    (
                        JobStatus.RUNNING.value,
                        JobStatus.CANCEL_REQUESTED.value,
                    )
                ),
                or_(
                    Job.budget_total_calls.is_(None),
                    Job.budget_reserved_calls + calls <= Job.budget_total_calls,
                ),
                or_(
                    Job.budget_total_tokens.is_(None),
                    Job.budget_reserved_tokens + tokens <= Job.budget_total_tokens,
                ),
            )
            .values(
                budget_reserved_calls=Job.budget_reserved_calls + calls,
                budget_reserved_tokens=Job.budget_reserved_tokens + tokens,
            )
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount == 1

    def consume_evaluation_budget(
        self, *, job_id: str, calls: int, tokens: int
    ) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.budget_used_calls + calls <= Job.budget_reserved_calls,
                Job.budget_used_tokens + tokens <= Job.budget_reserved_tokens,
            )
            .values(
                budget_used_calls=Job.budget_used_calls + calls,
                budget_used_tokens=Job.budget_used_tokens + tokens,
            )
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount == 1

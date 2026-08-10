"""Job submission, cancellation, retry, and conflict-matrix enforcement."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ResourceNotFoundException
from app.models import (
    FileRecord,
    Job,
    JobStatus,
    JobType,
    KnowledgeBase,
    RebuildStatus,
    RuntimeState,
    new_uuid,
    utc_now,
)
from app.repositories.job_repository import JobRepository


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)

    def submit(
        self,
        *,
        job_type: JobType,
        created_by_id: str | None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        resource_name_snapshot: str | None = None,
        payload: dict[str, Any] | None = None,
        collection_name: str | None = None,
        embedding_config_hash: str | None = None,
        dataset_sha256: str | None = None,
        evaluation_config_hash: str | None = None,
        evaluation_dataset_id: str | None = None,
        evaluation_mode: str | None = None,
        evaluation_run_name: str | None = None,
        budget_total_calls: int | None = None,
        budget_total_tokens: int | None = None,
        deadline_at: object | None = None,
        retry_of_job_id: str | None = None,
        run_after_seconds: float = 0,
        max_attempts: int = 1,
    ) -> Job:
        self._validate_conflicts(job_type, resource_type, resource_id, collection_name)
        now = utc_now()
        job = Job(
            id=new_uuid(),
            job_type=job_type.value,
            status=JobStatus.QUEUED.value,
            created_by_id=created_by_id,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name_snapshot=resource_name_snapshot,
            payload=payload or {},
            run_after=now + timedelta(seconds=run_after_seconds),
            retry_of_job_id=retry_of_job_id,
            max_attempts=max_attempts,
            collection_name=collection_name,
            embedding_config_hash=embedding_config_hash,
            dataset_sha256=dataset_sha256,
            evaluation_config_hash=evaluation_config_hash,
            evaluation_dataset_id=evaluation_dataset_id,
            evaluation_mode=evaluation_mode,
            evaluation_run_name=evaluation_run_name,
            budget_total_calls=budget_total_calls,
            budget_total_tokens=budget_total_tokens,
            deadline_at=deadline_at,
        )
        self.jobs.add(job)
        if job_type is JobType.BACKUP:
            self.db.add(
                RuntimeState(
                    key="BACKUP_DRAINING",
                    value={"status": "DRAINING"},
                    owner_job_id=job.id,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
        if job_type is JobType.FILE_PROCESS and resource_id:
            record = self.db.get(FileRecord, resource_id)
            if record is None:
                raise ResourceNotFoundException("文件不存在")
            record.processing_job_id = job.id
        elif job_type is JobType.KB_REBUILD and resource_id:
            knowledge_base = self.db.get(KnowledgeBase, resource_id)
            if knowledge_base is None:
                raise ResourceNotFoundException("知识库不存在")
            knowledge_base.rebuild_job_id = job.id
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.request_cancel(job_id, utc_now())
        if job is None:
            raise ResourceNotFoundException("Job 不存在")
        if (
            job.job_type == JobType.BACKUP.value
            and job.status == JobStatus.CANCELLED.value
        ):
            state = self.db.get(RuntimeState, "BACKUP_DRAINING")
            if state is not None and state.owner_job_id == job.id:
                self.db.delete(state)
        if job.status == JobStatus.CANCELLED.value:
            if job.job_type == JobType.FILE_PROCESS.value and job.resource_id:
                record = self.db.get(FileRecord, job.resource_id)
                if (
                    record is not None
                    and record.processing_job_id == job.id
                ):
                    record.processing_job_id = None
            elif (
                job.job_type == JobType.KB_REBUILD.value
                and job.resource_id
            ):
                knowledge_base = self.db.get(
                    KnowledgeBase, job.resource_id
                )
                if (
                    knowledge_base is not None
                    and knowledge_base.rebuild_job_id == job.id
                ):
                    knowledge_base.rebuild_job_id = None
        self.db.commit()
        self.db.refresh(job)
        return job

    def manual_retry(self, job_id: str, created_by_id: str | None) -> Job:
        original = self.jobs.get(job_id)
        if original is None:
            raise ResourceNotFoundException("Job 不存在")
        if original.status not in {
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }:
            raise ConflictException("只有失败或已取消 Job 可以手工 retry")
        if (
            original.resource_type == "KNOWLEDGE_BASE"
            and original.resource_id
            and self.db.get(KnowledgeBase, original.resource_id) is None
        ):
            raise ResourceNotFoundException(
                "原 Job 引用的知识库已不存在，不能 retry"
            )
        if (
            original.resource_type == "FILE"
            and original.resource_id
            and self.db.get(FileRecord, original.resource_id) is None
        ):
            raise ResourceNotFoundException(
                "原 Job 引用的文件已不存在，不能 retry"
            )
        retry_payload = dict(original.payload)
        if original.job_type == JobType.BACKUP.value:
            original_output = Path(
                str(retry_payload.get("output_path") or "backup.zip")
            )
            retry_output = original_output.with_name(
                f"{original_output.stem}.retry-{uuid4().hex[:10]}.zip"
            )
            retry_payload["output_path"] = str(retry_output)
            retry_payload["partial_path"] = str(
                retry_output.with_name(f"{retry_output.name}.partial")
            )
        retry_deadline = original.deadline_at
        if original.job_type == JobType.RAG_EVALUATION.value:
            runtime_seconds = int(
                retry_payload.get("max_runtime_seconds") or 0
            )
            if runtime_seconds <= 0:
                raise ConflictException(
                    "旧评估 Job 缺少运行时间预算，拒绝生成无效 retry"
                )
            retry_deadline = utc_now() + timedelta(
                seconds=runtime_seconds
            )
        return self.submit(
            job_type=JobType(original.job_type),
            created_by_id=created_by_id,
            resource_type=original.resource_type,
            resource_id=original.resource_id,
            resource_name_snapshot=original.resource_name_snapshot,
            payload=retry_payload,
            collection_name=original.collection_name,
            embedding_config_hash=original.embedding_config_hash,
            dataset_sha256=original.dataset_sha256,
            evaluation_config_hash=original.evaluation_config_hash,
            evaluation_dataset_id=original.evaluation_dataset_id,
            evaluation_mode=original.evaluation_mode,
            evaluation_run_name=original.evaluation_run_name,
            budget_total_calls=original.budget_total_calls,
            budget_total_tokens=original.budget_total_tokens,
            deadline_at=retry_deadline,
            retry_of_job_id=original.id,
            max_attempts=1 if original.job_type == JobType.BACKUP.value else original.max_attempts,
        )

    def _validate_conflicts(
        self,
        job_type: JobType,
        resource_type: str | None,
        resource_id: str | None,
        collection_name: str | None,
    ) -> None:
        if job_type is JobType.BACKUP:
            if self.jobs.has_nonterminal():
                raise ConflictException("存在其他非终态 Job，不能进入备份 draining")
            return
        if self.db.scalar(
            select(Job.id).where(
                Job.job_type == JobType.BACKUP.value,
                Job.status.in_(
                    (
                        JobStatus.QUEUED.value,
                        JobStatus.RUNNING.value,
                        JobStatus.CANCEL_REQUESTED.value,
                    )
                ),
            )
        ):
            raise ConflictException("备份正在 draining 或运行，拒绝新业务 Job")
        nonterminal = (
            JobStatus.QUEUED.value,
            JobStatus.RUNNING.value,
            JobStatus.CANCEL_REQUESTED.value,
        )
        if (
            job_type is not JobType.RAG_EVALUATION
            and resource_type
            and resource_id
            and self.db.scalar(
                select(Job.id).where(
                    Job.resource_type == resource_type,
                    Job.resource_id == resource_id,
                    Job.status.in_(nonterminal),
                    Job.job_type != JobType.RAG_EVALUATION.value,
                )
            )
        ):
            raise ConflictException("资源已有冲突的非终态维护 Job")
        if (
            job_type is JobType.KB_CLEANUP_RETIRED
            and collection_name
            and self.jobs.collection_is_pinned(collection_name)
        ):
            raise ConflictException("目标 Collection 正被评估 Job pin")

        if resource_type == "FILE" and resource_id:
            record = self.db.get(FileRecord, resource_id)
            if record is None:
                raise ResourceNotFoundException("文件不存在")
            knowledge_base = self.db.get(KnowledgeBase, record.knowledge_base_id)
            if (
                knowledge_base is None
                or knowledge_base.rebuild_status == RebuildStatus.BUILDING
                or self.db.scalar(
                    select(Job.id).where(
                        Job.resource_type == "KNOWLEDGE_BASE",
                        Job.resource_id == record.knowledge_base_id,
                        Job.status.in_(nonterminal),
                        Job.job_type != JobType.RAG_EVALUATION.value,
                    )
                )
            ):
                raise ConflictException("文件所属知识库正在执行维护操作")
            if (
                knowledge_base.active_collection_name
                and self.jobs.collection_is_pinned(
                    knowledge_base.active_collection_name
                )
            ):
                raise ConflictException("活动 Collection 正被评估 Job pin，不能写入")
        if (
            resource_type == "KNOWLEDGE_BASE"
            and resource_id
            and job_type is not JobType.RAG_EVALUATION
        ):
            if self.db.scalar(
                select(Job.id).where(
                    Job.resource_type == "FILE",
                    Job.status.in_(
                        (
                            JobStatus.QUEUED.value,
                            JobStatus.RUNNING.value,
                            JobStatus.CANCEL_REQUESTED.value,
                        )
                    ),
                    Job.resource_id.in_(
                        select(FileRecord.id).where(
                            FileRecord.knowledge_base_id == resource_id
                        )
                    ),
                )
            ):
                raise ConflictException("知识库存在非终态文件 Job")

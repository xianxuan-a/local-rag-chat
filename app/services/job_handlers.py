"""Default business handlers registered with the single Job worker."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.config import Settings
from app.database.sqlite import SessionFactory
from app.models import Job, JobStatus, JobType, utc_now
from app.repositories.job_repository import JobRepository
from app.services.backup_service import OnlineBackupService
from app.services.evaluation_service import EvaluationService
from app.services.file_service import FileService
from app.services.job_worker import (
    JobDeferred,
    JobExecutionContext,
    JobHandler,
)
from app.services.knowledge_base_rebuild_service import (
    KnowledgeBaseRebuildService,
)
from app.services.runtime_coordinator import RuntimeCoordinator


def build_default_job_handlers(
    *,
    session_factory: SessionFactory,
    settings: Settings,
    runtime: RuntimeCoordinator,
) -> dict[JobType, JobHandler]:
    def file_process(
        context: JobExecutionContext, detached_job: Job
    ) -> dict[str, Any]:
        with session_factory() as db:
            try:
                record = FileService(db, settings, runtime).process_file(
                    str(detached_job.resource_id),
                    job_id=detached_job.id,
                    checkpoint=context.checkpoint,
                )
                return {
                    "file_id": record.id,
                    "status": (
                        record.status.value
                        if hasattr(record.status, "value")
                        else record.status
                    ),
                    "chunk_count": record.chunk_count,
                }
            except Exception:
                db.rollback()
                from app.models import FileRecord, FileStatus

                record = db.get(FileRecord, detached_job.resource_id)
                if (
                    record is not None
                    and record.processing_job_id == detached_job.id
                    and record.status != FileStatus.PROCESSING
                ):
                    record.processing_job_id = None
                    db.commit()
                raise

    def rebuild(
        context: JobExecutionContext, detached_job: Job
    ) -> dict[str, Any]:
        with session_factory() as db:
            response = KnowledgeBaseRebuildService(
                db, settings, runtime
            ).rebuild(
                str(detached_job.resource_id),
                job_id=detached_job.id,
                checkpoint=context.checkpoint,
            )
            data = response.model_dump(mode="json")
            if not response.switched and response.status != "SUCCESS":
                raise RuntimeError(
                    f"知识库重建未切换：{response.status}"
                )
            return data

    def cleanup(
        context: JobExecutionContext, detached_job: Job
    ) -> dict[str, Any]:
        with session_factory() as db:
            current = db.get(Job, detached_job.id)
            if (
                current is not None
                and current.collection_name
                and JobRepository(db).collection_is_pinned(
                    current.collection_name,
                    exclude_job_id=current.id,
                )
            ):
                # Waiting for a pin is not an execution failure and must not
                # consume the bounded retry allowance on every lease claim.
                current.attempt = max(0, current.attempt - 1)
                current.status = JobStatus.QUEUED.value
                current.run_after = utc_now() + timedelta(seconds=30)
                current.lease_owner = None
                current.lease_expires_at = None
                current.last_heartbeat_at = None
                current.stage = "WAITING_FOR_EVALUATION_PIN"
                db.commit()
                raise JobDeferred("Cleanup Collection 正被评估 Job pin")
            context.checkpoint("CLEANUP_RECHECKED", 40, force=True)
            return KnowledgeBaseRebuildService(
                db, settings, runtime
            ).cleanup_indexes(
                str(detached_job.resource_id),
                cleanup_previous=bool(
                    detached_job.payload.get("cleanup_previous", False)
                ),
                cleanup_orphans=bool(
                    detached_job.payload.get("cleanup_orphans", False)
                ),
            )

    def evaluation(
        context: JobExecutionContext, detached_job: Job
    ) -> dict[str, Any]:
        with session_factory() as db:
            job = db.get(Job, detached_job.id)
            if job is None:
                raise RuntimeError("评估 Job 不存在")
            effective = runtime.effective_settings()
            snapshot = job.payload.get("chat_snapshot")
            if isinstance(snapshot, dict):
                effective = effective.model_copy(
                    update={
                        "CHAT_MODEL": snapshot.get("chat_model"),
                        "CHAT_TEMPERATURE": snapshot.get(
                            "chat_temperature",
                            effective.CHAT_TEMPERATURE,
                        ),
                        "CHAT_MAX_TOKENS": snapshot.get(
                            "chat_max_tokens", effective.CHAT_MAX_TOKENS
                        ),
                        "CHAT_TIMEOUT_SECONDS": snapshot.get(
                            "chat_timeout_seconds",
                            effective.CHAT_TIMEOUT_SECONDS,
                        ),
                        "CHAT_MAX_ATTEMPTS": snapshot.get(
                            "chat_max_attempts",
                            effective.CHAT_MAX_ATTEMPTS,
                        ),
                        "RAG_CONTEXT_MAX_CHARS": snapshot.get(
                            "rag_context_max_chars",
                            effective.RAG_CONTEXT_MAX_CHARS,
                        ),
                    }
                )
            return EvaluationService(
                db, effective, runtime
            ).run(job, context.checkpoint)

    def backup(
        context: JobExecutionContext, detached_job: Job
    ) -> dict[str, Any]:
        with session_factory() as db:
            job = db.get(Job, detached_job.id)
            if job is None:
                raise RuntimeError("备份 Job 不存在")
            return OnlineBackupService(db, settings, runtime).run(
                job, context.checkpoint
            )

    return {
        JobType.FILE_PROCESS: file_process,
        JobType.KB_REBUILD: rebuild,
        JobType.KB_CLEANUP_RETIRED: cleanup,
        JobType.RAG_EVALUATION: evaluation,
        JobType.BACKUP: backup,
    }

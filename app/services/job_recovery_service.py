"""Business-aware recovery for jobs whose durable lease has expired."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from enum import Enum
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logger import get_logger
from app.models import (
    FileRecord,
    FileStatus,
    Job,
    JobStatus,
    JobType,
    KnowledgeBase,
    RebuildStatus,
    RuntimeState,
    utc_now,
)
from app.services.runtime_coordinator import RuntimeCoordinator


logger = get_logger(__name__)


class RecoveryDisposition(str, Enum):
    RETRY_READY = "RETRY_READY"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class JobRecoveryService:
    """Reconcile business state before a job is ever made claimable again."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        runtime: RuntimeCoordinator,
    ) -> None:
        self.db = db
        self.settings = settings
        self.runtime = runtime

    def recover_expired(self, job: Job) -> RecoveryDisposition:
        if job.status == JobStatus.CANCEL_REQUESTED.value:
            return self._fail(
                job,
                status=JobStatus.CANCELLED,
                code="CANCELLED_AFTER_LEASE_EXPIRY",
                message="取消请求在租约过期恢复点生效",
            )
        job_type = JobType(job.job_type)
        if job_type is JobType.BACKUP:
            return self._recover_backup(job)
        if job_type is JobType.FILE_PROCESS:
            return self._recover_file(job)
        if job_type is JobType.KB_REBUILD:
            return self._recover_rebuild(job)
        if job_type is JobType.KB_CLEANUP_RETIRED:
            return self._recover_cleanup(job)
        if job_type is JobType.RAG_EVALUATION:
            return self._recover_evaluation(job)
        return self._fail(
            job,
            code="UNKNOWN_JOB_TYPE",
            message="未知 Job 类型不能安全恢复",
        )

    def _recover_backup(self, job: Job) -> RecoveryDisposition:
        partial_value = job.payload.get("partial_path")
        if isinstance(partial_value, str) and partial_value:
            partial = Path(partial_value).expanduser().resolve()
            if partial.is_file():
                quarantine = partial.with_name(
                    f"{partial.name}.abandoned-{job.id}"
                )
                if quarantine.exists():
                    return self._fail(
                        job,
                        code="BACKUP_PARTIAL_QUARANTINE_CONFLICT",
                        message="备份 partial 隔离目标已存在，需人工处理",
                    )
                os.replace(partial, quarantine)
        state = self.db.get(RuntimeState, "BACKUP_DRAINING")
        if state is not None and state.owner_job_id == job.id:
            self.db.delete(state)
        return self._fail(
            job,
            code="BACKUP_LEASE_EXPIRED_NOT_RESUMED",
            message="BACKUP 永不自动续跑或重试；请由管理员创建新 Job",
        )

    def _recover_file(self, job: Job) -> RecoveryDisposition:
        record = self.db.get(FileRecord, job.resource_id)
        if record is None:
            return self._fail(
                job, code="FILE_MISSING", message="恢复时文件记录已不存在"
            )
        if (
            record.status == FileStatus.PROCESSING
            and record.processing_job_id != job.id
        ):
            return self._fail(
                job,
                code="FILE_PROCESSING_OWNED_BY_OTHER_JOB",
                message="PROCESSING 状态属于另一个 Job，拒绝重置",
            )
        knowledge_base = self.db.get(KnowledgeBase, record.knowledge_base_id)
        if knowledge_base is None:
            record.status = FileStatus.FAILED
            record.error_message = "RESTORED_REBUILD_REQUIRED"
            record.processing_job_id = None
            return self._fail(
                job,
                code="COLLECTION_UNVERIFIABLE_REBUILD_REQUIRED",
                message="活动 Collection 缺失或不可验证，必须整库重建",
            )
        if record.status == FileStatus.SUCCESS:
            try:
                if (
                    not knowledge_base.active_collection_name
                    or not knowledge_base.active_embedding_config_hash
                ):
                    raise RuntimeError("active collection missing")
                completed = self.runtime.vector_store.snapshot_file(
                    knowledge_base.active_collection_name,
                    knowledge_base_id=knowledge_base.id,
                    file_id=record.id,
                    expected_config_hash=(
                        knowledge_base.active_embedding_config_hash
                    ),
                )
                expected_count = int(
                    job.payload.get("expected_chunk_count")
                    or record.chunk_count
                )
                vector_complete = (
                    expected_count > 0
                    and len(completed.ids) == expected_count
                    and len(completed.ids) == record.chunk_count
                    and all(
                        metadata.get("processing_job_id") == job.id
                        and int(
                            metadata.get("expected_chunk_count") or -1
                        )
                        == expected_count
                        for metadata in completed.metadatas
                    )
                )
            except Exception:
                vector_complete = False
            if vector_complete:
                record.processing_job_id = None
                return self._succeed(
                    job,
                    {
                        "recovered": True,
                        "file_id": record.id,
                        "chunk_count": record.chunk_count,
                    },
                )
            record.status = FileStatus.FAILED
            record.error_message = "RECOVERED_RETRY_FROM_SCRATCH"
            record.processing_job_id = job.id
            return self._requeue(
                job, "RECOVERED_FILE_DATABASE_VECTOR_MISMATCH"
            )
        if not knowledge_base.active_collection_name:
            candidate = knowledge_base.building_collection_name
            if candidate and self.runtime.vector_store.collection_exists(candidate):
                try:
                    snapshot = self.runtime.vector_store.snapshot_file(
                        candidate,
                        knowledge_base_id=knowledge_base.id,
                        file_id=record.id,
                        expected_config_hash=(
                            knowledge_base.building_embedding_config_hash
                        ),
                    )
                    if snapshot.ids and not all(
                        metadata.get("processing_job_id") == job.id
                        for metadata in snapshot.metadatas
                    ):
                        raise RuntimeError("candidate vector ownership mismatch")
                    if snapshot.ids:
                        self.runtime.vector_store.delete_ids(
                            candidate, snapshot.ids
                        )
                    self.runtime.vector_store.set_lifecycle(
                        candidate, "FAILED"
                    )
                    knowledge_base.rebuild_status = RebuildStatus.FAILED
                except Exception:
                    record.status = FileStatus.FAILED
                    record.error_message = "RESTORED_REBUILD_REQUIRED"
                    record.processing_job_id = None
                    return self._fail(
                        job,
                        code="INITIAL_COLLECTION_UNVERIFIABLE",
                        message="首次候选 Collection 不可验证，需人工重建",
                    )
            elif candidate:
                knowledge_base.rebuild_status = RebuildStatus.FAILED
            record.status = FileStatus.FAILED
            record.error_message = "RECOVERED_RETRY_FROM_SCRATCH"
            record.processing_job_id = job.id
            return self._requeue(
                job, "RECOVERED_INITIAL_FILE_FROM_SCRATCH"
            )
        try:
            snapshot = self.runtime.vector_store.snapshot_file(
                knowledge_base.active_collection_name,
                knowledge_base_id=knowledge_base.id,
                file_id=record.id,
                expected_config_hash=knowledge_base.active_embedding_config_hash,
            )
        except Exception:
            record.status = FileStatus.FAILED
            record.error_message = "RESTORED_REBUILD_REQUIRED"
            record.processing_job_id = None
            return self._fail(
                job,
                code="COLLECTION_UNVERIFIABLE_REBUILD_REQUIRED",
                message="向量状态不可验证，必须整库重建",
            )

        if snapshot.ids:
            owned_by_this_job = [
                metadata.get("processing_job_id") == job.id
                for metadata in snapshot.metadatas
            ]
            if any(owned_by_this_job) and not all(owned_by_this_job):
                return self._fail(
                    job,
                    code="VECTOR_OWNERSHIP_UNCERTAIN",
                    message="Collection 同时含本 Job 与其他 run 的向量，拒绝破坏性恢复",
                )
            if all(owned_by_this_job):
                self.runtime.vector_store.delete_ids(
                    knowledge_base.active_collection_name, snapshot.ids
                )
        record.status = FileStatus.FAILED
        record.error_message = "RECOVERED_RETRY_FROM_SCRATCH"
        record.processing_job_id = job.id
        return self._requeue(job, "RECOVERED_FILE_REPLACE_FROM_SCRATCH")

    def _recover_rebuild(self, job: Job) -> RecoveryDisposition:
        knowledge_base = self.db.get(KnowledgeBase, job.resource_id)
        if knowledge_base is None:
            return self._fail(
                job, code="KB_MISSING", message="恢复时知识库已不存在"
            )
        candidate = job.collection_name or knowledge_base.building_collection_name
        if (
            candidate
            and knowledge_base.active_collection_name == candidate
            and knowledge_base.rebuild_status != RebuildStatus.BUILDING
        ):
            try:
                expected_hash = (
                    job.embedding_config_hash
                    or knowledge_base.active_embedding_config_hash
                )
                if (
                    not expected_hash
                    or knowledge_base.active_embedding_config_hash
                    != expected_hash
                ):
                    raise RuntimeError("switched configuration mismatch")
                run_id = str(job.payload.get("rebuild_run_id") or "")
                counts: dict[str, int] = {}
                file_records = list(knowledge_base.files)
                for record in file_records:
                    snapshot = self.runtime.vector_store.snapshot_file(
                        candidate,
                        knowledge_base_id=knowledge_base.id,
                        file_id=record.id,
                        expected_config_hash=expected_hash,
                    )
                    if (
                        len(snapshot.ids) != record.chunk_count
                        or not snapshot.ids
                        or not all(
                            metadata.get("processing_job_id") == job.id
                            and metadata.get("vector_run_id") == run_id
                            for metadata in snapshot.metadatas
                        )
                    ):
                        raise RuntimeError(
                            "switched collection count or run ownership mismatch"
                        )
                    counts[record.id] = len(snapshot.ids)
                self.runtime.vector_store.validate_whole_collection(
                    name=candidate,
                    knowledge_base_id=knowledge_base.id,
                    config_hash=expected_hash,
                    expected_file_ids={record.id for record in file_records},
                    expected_counts=counts,
                    role="active",
                )
            except Exception:
                return self._fail(
                    job,
                    code="SWITCHED_COLLECTION_UNVERIFIABLE",
                    message="数据库已切换但 Collection 无法验证，需人工处理",
                )
            knowledge_base.rebuild_job_id = None
            return self._succeed(
                job,
                {
                    "recovered": True,
                    "switched": True,
                    "collection_name": candidate,
                    "vector_count": sum(counts.values()),
                },
            )
        if (
            knowledge_base.rebuild_status == RebuildStatus.BUILDING
            and knowledge_base.rebuild_job_id != job.id
        ):
            return self._fail(
                job,
                code="REBUILD_OWNED_BY_OTHER_JOB",
                message="BUILDING 状态属于另一个 Job，拒绝重置",
            )
        if candidate and self.runtime.vector_store.collection_exists(candidate):
            expected_hash = (
                job.embedding_config_hash
                or knowledge_base.building_embedding_config_hash
            )
            source_collection = job.payload.get("source_collection")
            source_previous = job.payload.get("source_previous")
            if (
                knowledge_base.active_collection_name != source_collection
                or knowledge_base.previous_collection_name != source_previous
            ):
                return self._fail(
                    job,
                    code="REBUILD_POINTER_CHANGED",
                    message="源指针已被其他操作改变，必须人工处理",
                )
            try:
                file_records = list(knowledge_base.files)
                expected_counts: dict[str, int] = {}
                rebuild_run_id = str(
                    job.payload.get("rebuild_run_id") or ""
                )
                if not rebuild_run_id and file_records:
                    raise RuntimeError("rebuild run id missing")
                for record in file_records:
                    snapshot = self.runtime.vector_store.snapshot_file(
                        candidate,
                        knowledge_base_id=knowledge_base.id,
                        file_id=record.id,
                        expected_config_hash=str(expected_hash),
                    )
                    if not snapshot.ids:
                        raise RuntimeError("candidate file vectors missing")
                    declared_counts = {
                        int(metadata.get("expected_chunk_count") or -1)
                        for metadata in snapshot.metadatas
                    }
                    if (
                        len(declared_counts) != 1
                        or next(iter(declared_counts)) != len(snapshot.ids)
                        or not all(
                            metadata.get("processing_job_id") == job.id
                            and metadata.get("vector_run_id")
                            == rebuild_run_id
                            for metadata in snapshot.metadatas
                        )
                    ):
                        raise RuntimeError(
                            "candidate vectors incomplete or owned by another run"
                        )
                    expected_counts[record.id] = len(snapshot.ids)
                self.runtime.vector_store.validate_whole_collection(
                    name=candidate,
                    knowledge_base_id=knowledge_base.id,
                    config_hash=str(expected_hash),
                    expected_file_ids={record.id for record in file_records},
                    expected_counts=expected_counts,
                )
                counts = expected_counts
            except Exception:
                counts = {}
            if counts or not list(knowledge_base.files):
                knowledge_base.cleanup_collection_name = (
                    knowledge_base.previous_collection_name
                )
                knowledge_base.previous_collection_name = (
                    knowledge_base.active_collection_name
                )
                knowledge_base.previous_embedding_config_hash = (
                    knowledge_base.active_embedding_config_hash
                )
                knowledge_base.active_collection_name = candidate
                knowledge_base.active_embedding_config_hash = expected_hash
                knowledge_base.building_collection_name = None
                knowledge_base.building_embedding_config_hash = None
                knowledge_base.rebuild_status = RebuildStatus.IDLE
                knowledge_base.rebuild_run_id = None
                knowledge_base.rebuild_job_id = None
                knowledge_base.building_started_at = None
                for record in knowledge_base.files:
                    count = counts.get(record.id, 0)
                    record.chunk_count = count
                    record.has_active_vectors = count > 0
                    record.active_index_config_hash = (
                        expected_hash if count else None
                    )
                self.db.commit()
                try:
                    self.runtime.vector_store.set_lifecycle(
                        candidate, "ACTIVE"
                    )
                    if source_collection:
                        self.runtime.vector_store.set_lifecycle(
                            str(source_collection), "RETIRED"
                        )
                except Exception:
                    logger.exception(
                        "恢复切换已提交，但 Collection lifecycle 更新失败"
                    )
                return self._succeed(
                    job,
                    {
                        "recovered": True,
                        "switched": True,
                        "collection_name": candidate,
                    },
                )
            try:
                self.runtime.vector_store.set_lifecycle(candidate, "FAILED")
            except Exception:
                logger.exception("无法将遗留候选 Collection 标记为 FAILED")
                return self._fail(
                    job,
                    code="CANDIDATE_STATE_UNCERTAIN",
                    message="候选 Collection 状态不确定，需人工处理",
                )
        knowledge_base.rebuild_status = RebuildStatus.FAILED
        knowledge_base.rebuild_job_id = job.id
        return self._requeue(job, "RECOVERED_REBUILD_FROM_SCRATCH")

    def _recover_cleanup(self, job: Job) -> RecoveryDisposition:
        knowledge_base = self.db.get(KnowledgeBase, job.resource_id)
        if knowledge_base is None:
            return self._fail(
                job,
                code="KB_MISSING",
                message="恢复 cleanup 时知识库已不存在",
            )
        target = job.collection_name or knowledge_base.cleanup_collection_name
        if target is None:
            return self._succeed(
                job, {"recovered": True, "already_missing": True}
            )
        if knowledge_base.cleanup_collection_name != target:
            return self._fail(
                job,
                code="CLEANUP_POINTER_CHANGED",
                message="Cleanup 指针已变化，拒绝删除",
            )
        if not self.runtime.vector_store.collection_exists(target):
            knowledge_base.cleanup_collection_name = None
            return self._succeed(
                job,
                {
                    "recovered": True,
                    "already_missing": True,
                    "collection_name": target,
                },
            )
        from app.repositories.job_repository import JobRepository

        if JobRepository(self.db).collection_is_pinned(
            target, exclude_job_id=job.id
        ):
            job.attempt = max(0, job.attempt - 1)
            disposition = self._requeue(job, "WAITING_FOR_EVALUATION_PIN")
            job.run_after = utc_now() + timedelta(seconds=30)
            self.db.commit()
            return disposition
        return self._requeue(job, "RECOVERED_CLEANUP_RECHECK")

    def _recover_evaluation(self, job: Job) -> RecoveryDisposition:
        configured_report = job.report_path or job.payload.get("report_path")
        if isinstance(configured_report, str) and configured_report:
            verified = self._verify_complete_evaluation_report(
                job, Path(configured_report)
            )
            if verified is not None:
                report, digest = verified
                job.report_path = str(report)
                job.report_sha256 = digest
                return self._succeed(
                    job,
                    {
                        "recovered": True,
                        "report_path": str(report),
                        "report_sha256": digest,
                    },
                )
        case_count = int(job.payload.get("case_count") or 0)
        calls_per_case = 1 if job.evaluation_mode == "retrieval" else 2
        remaining_calls = (
            None
            if job.budget_total_calls is None
            else job.budget_total_calls - job.budget_reserved_calls
        )
        if (
            remaining_calls is not None
            and remaining_calls < case_count * calls_per_case
        ):
            return self._fail(
                job,
                code="EVALUATION_BUDGET_EXHAUSTED_AFTER_CRASH",
                message="剩余调用预算不足以从案例 0 原子重跑",
            )
        return self._requeue(job, "RECOVERED_EVALUATION_RESTART_FROM_ZERO")

    def _verify_complete_evaluation_report(
        self, job: Job, configured_path: Path
    ) -> tuple[Path, str] | None:
        root = (self.settings.EVALUATION_DIR / "reports").resolve()
        if configured_path.is_symlink():
            return None
        try:
            report = configured_path.resolve(strict=True)
            report.relative_to(root)
        except (OSError, ValueError):
            return None
        try:
            if (
                not report.is_file()
                or report.stat().st_size > 20 * 1024 * 1024
            ):
                return None
            raw = report.read_bytes()
        except OSError:
            return None
        digest = hashlib.sha256(raw).hexdigest()
        if job.report_sha256 and digest != job.report_sha256:
            return None
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            case_count = int(job.payload.get("case_count") or 0)
            success_count = int(payload.get("success_count") or 0)
            failure_count = int(payload.get("failure_count") or 0)
        except (TypeError, ValueError):
            return None
        cases = payload.get("cases") if isinstance(payload, dict) else None
        if (
            payload.get("format") != "local-rag-evaluation-report"
            or payload.get("format_version") not in {1, 2}
            or payload.get("job_id") != job.id
            or payload.get("dataset_sha256") != job.dataset_sha256
            or str(payload.get("knowledge_base_id"))
            != str(job.resource_id)
            or payload.get("collection_name") != job.collection_name
            or payload.get("embedding_config_hash")
            != job.embedding_config_hash
            or payload.get("evaluation_config_hash")
            != job.evaluation_config_hash
            or payload.get("case_count") != case_count
            or not isinstance(cases, list)
            or len(cases) != case_count
            or success_count + failure_count != case_count
        ):
            return None
        if (
            payload.get("format_version") == 2
            and payload.get("mode") != (job.evaluation_mode or "rag")
        ):
            return None
        return report, digest

    def _requeue(self, job: Job, stage: str) -> RecoveryDisposition:
        if job.attempt >= job.max_attempts:
            return self._fail(
                job,
                code="RECOVERY_RETRY_ATTEMPTS_EXHAUSTED",
                message=(
                    "业务恢复需要重新执行，但 Job 的最大执行次数已耗尽；"
                    "请人工核对后创建手工 retry Job"
                ),
            )
        now = utc_now()
        job.status = JobStatus.QUEUED.value
        job.run_after = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_heartbeat_at = None
        job.stage = stage
        job.error_code = None
        job.error_message = None
        self.db.commit()
        return RecoveryDisposition.RETRY_READY

    def _succeed(
        self, job: Job, result: dict[str, object]
    ) -> RecoveryDisposition:
        job.status = JobStatus.SUCCEEDED.value
        job.result = result
        job.progress = 100
        job.stage = "RECOVERED_SUCCEEDED"
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_heartbeat_at = None
        job.finished_at = utc_now()
        self.db.commit()
        return RecoveryDisposition.SUCCEEDED

    def _fail(
        self,
        job: Job,
        *,
        code: str,
        message: str,
        status: JobStatus = JobStatus.FAILED,
    ) -> RecoveryDisposition:
        job.status = status.value
        job.stage = "RECOVERY_FAILED"
        job.error_code = code
        job.error_message = message
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_heartbeat_at = None
        job.finished_at = utc_now()
        self.db.commit()
        return RecoveryDisposition.FAILED

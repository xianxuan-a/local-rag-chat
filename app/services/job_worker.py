"""Single business-worker thread with durable leases and control-plane heartbeat."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.observability import (
    FILE_PROCESS_TERMINALS,
    JOB_DURATION,
    JOB_TERMINALS,
)
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
from app.repositories.job_repository import JobRepository
from app.database.sqlite import SessionFactory
from app.services.job_recovery_service import JobRecoveryService
from app.services.runtime_coordinator import RuntimeCoordinator


logger = get_logger(__name__)
JobHandler = Callable[["JobExecutionContext", Job], dict[str, Any] | None]


class JobCancelled(RuntimeError):
    pass


class JobDeferred(RuntimeError):
    """Handler durably returned itself to QUEUED without failing."""


class JobExecutionContext:
    def __init__(
        self,
        *,
        job_id: str,
        lease_owner: str,
        session_factory: SessionFactory,
        settings: Settings,
    ) -> None:
        self.job_id = job_id
        self.lease_owner = lease_owner
        self.session_factory = session_factory
        self.settings = settings
        self._last_progress_at = 0.0
        self._last_stage: str | None = None
        self._heartbeat_stop = threading.Event()
        self._lease_lost = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def start_heartbeat(self) -> None:
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"job-heartbeat-{self.job_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(
                timeout=self.settings.JOB_HEARTBEAT_SECONDS + 1
            )
            self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(
            self.settings.JOB_HEARTBEAT_SECONDS
        ):
            try:
                with self.session_factory() as db:
                    renewed = JobRepository(db).heartbeat(
                        job_id=self.job_id,
                        lease_owner=self.lease_owner,
                        now=utc_now(),
                        lease_seconds=self.settings.JOB_LEASE_SECONDS,
                    )
                    db.commit()
                if not renewed:
                    self._lease_lost.set()
                    return
            except OperationalError:
                logger.warning(
                    "Job 控制面心跳遇到 SQLite 暂时性错误（job_id=%s）",
                    self.job_id,
                    exc_info=True,
                )
            except Exception:
                self._lease_lost.set()
                logger.exception(
                    "Job 控制面心跳失败（job_id=%s）", self.job_id
                )
                return

    def checkpoint(
        self, stage: str, progress: int | None = None, *, force: bool = False
    ) -> None:
        import time

        if self._lease_lost.is_set():
            raise JobCancelled("Job 租约已丢失")
        now_monotonic = time.monotonic()
        stage_changed = stage != self._last_stage
        write_progress = (
            force
            or stage_changed
            or now_monotonic - self._last_progress_at
            >= self.settings.JOB_PROGRESS_MIN_INTERVAL_SECONDS
        )
        with self.session_factory() as db:
            job = db.get(Job, self.job_id)
            if job is None or job.lease_owner != self.lease_owner:
                raise JobCancelled("Job 租约已丢失")
            if job.status == JobStatus.CANCEL_REQUESTED.value:
                raise JobCancelled("Job 已请求取消")
            if not write_progress:
                return
            repository = JobRepository(db)
            if not repository.heartbeat(
                job_id=self.job_id,
                lease_owner=self.lease_owner,
                now=utc_now(),
                lease_seconds=self.settings.JOB_LEASE_SECONDS,
                progress=progress if write_progress else None,
                stage=stage if write_progress else None,
            ):
                raise JobCancelled("Job 心跳条件更新失败")
            db.commit()
        if write_progress:
            self._last_progress_at = now_monotonic
            self._last_stage = stage


class JobWorker:
    """Claim and execute at most one business job at a time."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: Settings,
        runtime: RuntimeCoordinator,
        handlers: dict[JobType, JobHandler] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.runtime = runtime
        self.handlers = handlers or {}
        self.lease_owner = f"worker-{uuid4()}"
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self.recover_orphaned_file_states()
        self.recover_orphaned_building_states()
        self.recover_expired()
        self._thread = threading.Thread(
            target=self._run,
            name="local-rag-job-worker",
            daemon=True,
        )
        self._thread.start()

    def recover_orphaned_file_states(self) -> int:
        """Fail PROCESSING records that no durable non-terminal Job owns."""

        recovered = 0
        with self.session_factory() as db:
            records = list(
                db.scalars(
                    select(FileRecord).where(
                        FileRecord.status == FileStatus.PROCESSING
                    )
                ).all()
            )
            for record in records:
                job = (
                    db.get(Job, record.processing_job_id)
                    if record.processing_job_id is not None
                    else None
                )
                if job is not None and job.status in {
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.CANCEL_REQUESTED.value,
                }:
                    continue
                record.status = FileStatus.FAILED
                record.error_message = "ORPHANED_PROCESSING_STATE"
                record.processing_job_id = None
                recovered += 1
            if recovered:
                db.commit()
                logger.warning(
                    "启动时恢复了 %s 条无有效 Job 的 PROCESSING 文件记录",
                    recovered,
                )
        return recovered

    def recover_orphaned_building_states(self) -> int:
        """Mark BUILDING pointers without a durable live rebuild Job as failed."""

        recovered = 0
        with self.session_factory() as db:
            knowledge_bases = list(
                db.scalars(
                    select(KnowledgeBase).where(
                        KnowledgeBase.rebuild_status
                        == RebuildStatus.BUILDING
                    )
                ).all()
            )
            for knowledge_base in knowledge_bases:
                job = (
                    db.get(Job, knowledge_base.rebuild_job_id)
                    if knowledge_base.rebuild_job_id is not None
                    else None
                )
                if (
                    job is not None
                    and job.job_type == JobType.KB_REBUILD.value
                    and job.resource_id == knowledge_base.id
                    and job.status
                    in {
                        JobStatus.QUEUED.value,
                        JobStatus.RUNNING.value,
                        JobStatus.CANCEL_REQUESTED.value,
                    }
                ):
                    continue
                knowledge_base.rebuild_status = RebuildStatus.FAILED
                recovered += 1
            if recovered:
                db.commit()
                logger.warning(
                    "启动时标记了 %s 个无有效 Job 的遗留 BUILDING 状态",
                    recovered,
                )
        return recovered

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def wake(self) -> None:
        self._wake_event.set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def recover_expired(self) -> None:
        with self.session_factory() as db:
            expired_ids = [
                job.id for job in JobRepository(db).expired(utc_now())
            ]
        for job_id in expired_ids:
            with self.session_factory() as db:
                job = db.get(Job, job_id)
                if (
                    job is None
                    or job.lease_expires_at is None
                    or job.lease_expires_at >= utc_now()
                ):
                    continue
                JobRecoveryService(
                    db, self.settings, self.runtime
                ).recover_expired(job)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.recover_expired()
            job = self._claim()
            if job is None:
                self._wake_event.wait(self.settings.JOB_POLL_INTERVAL_SECONDS)
                self._wake_event.clear()
                continue
            self._execute(job)

    def _claim(self) -> Job | None:
        with self.session_factory() as db:
            job = JobRepository(db).claim_next(
                lease_owner=self.lease_owner,
                now=utc_now(),
                lease_seconds=self.settings.JOB_LEASE_SECONDS,
            )
            db.commit()
            if job is not None:
                db.expunge(job)
            return job

    def _execute(self, job: Job) -> None:
        logger.info(
            "Job started job_id=%s job_type=%s attempt=%s max_attempts=%s",
            job.id,
            job.job_type,
            job.attempt,
            job.max_attempts,
        )
        context = JobExecutionContext(
            job_id=job.id,
            lease_owner=self.lease_owner,
            session_factory=self.session_factory,
            settings=self.settings,
        )
        handler = self.handlers.get(JobType(job.job_type))
        if handler is None:
            self._finish(
                job.id,
                JobStatus.FAILED,
                error_code="NO_JOB_HANDLER",
                error_message=f"Job handler 未注册：{job.job_type}",
            )
            return
        try:
            context.checkpoint("STARTING", 0, force=True)
            context.start_heartbeat()
            result = handler(context, job) or {}
            self._finish(job.id, JobStatus.SUCCEEDED, result=result)
        except JobDeferred:
            return
        except JobCancelled as exc:
            self._finish(
                job.id,
                JobStatus.CANCELLED,
                error_code="CANCELLED_AT_CHECKPOINT",
                error_message=str(exc),
            )
        except OperationalError as exc:
            context.stop_heartbeat()
            if self._recover_transient_failure(job.id, exc):
                return
            self._finish(
                job.id,
                JobStatus.FAILED,
                error_code="SQLITE_OPERATION_FAILED",
                error_message="SQLite 操作失败且重试预算已耗尽",
            )
        except Exception as exc:
            logger.exception("Job 执行失败（job_id=%s）", job.id)
            self._finish(
                job.id,
                JobStatus.FAILED,
                error_code=type(exc).__name__.upper(),
                error_message=str(exc)[:2000],
            )
        finally:
            context.stop_heartbeat()

    def _recover_transient_failure(
        self, job_id: str, exc: Exception
    ) -> bool:
        with self.session_factory() as db:
            job = db.get(Job, job_id)
            if (
                job is None
                or job.job_type == JobType.BACKUP.value
                or job.attempt >= job.max_attempts
            ):
                return False
            job.lease_expires_at = utc_now() - timedelta(seconds=1)
            db.commit()
            disposition = JobRecoveryService(
                db, self.settings, self.runtime
            ).recover_expired(job)
            if disposition.value == "RETRY_READY":
                job.run_after = utc_now() + timedelta(
                    seconds=min(30, 2 ** job.attempt)
                )
                job.stage = "TRANSIENT_RECOVERY_RETRY"
                job.error_code = "TRANSIENT_RETRY"
                job.error_message = str(exc)[:1000]
                db.commit()
            return True

    def _finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: dict[str, object] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            job = db.get(Job, job_id)
            updated = JobRepository(db).finish(
                job_id=job_id,
                lease_owner=self.lease_owner,
                status=status,
                now=utc_now(),
                result=result,
                error_code=error_code,
                error_message=error_message,
            )
            if updated and job is not None:
                if job.job_type == JobType.BACKUP.value:
                    state = db.get(RuntimeState, "BACKUP_DRAINING")
                    if (
                        state is not None
                        and state.owner_job_id == job.id
                    ):
                        db.delete(state)
                elif (
                    status is not JobStatus.SUCCEEDED
                    and job.job_type == JobType.FILE_PROCESS.value
                    and job.resource_id
                ):
                    record = db.get(FileRecord, job.resource_id)
                    if (
                        record is not None
                        and record.processing_job_id == job.id
                    ):
                        record.processing_job_id = None
                        if record.status == FileStatus.PROCESSING:
                            record.status = FileStatus.FAILED
                            record.error_message = (
                                error_code or "JOB_TERMINATED"
                            )
                elif (
                    status is not JobStatus.SUCCEEDED
                    and job.job_type == JobType.KB_REBUILD.value
                    and job.resource_id
                ):
                    knowledge_base = db.get(
                        KnowledgeBase, job.resource_id
                    )
                    if (
                        knowledge_base is not None
                        and knowledge_base.rebuild_job_id == job.id
                    ):
                        knowledge_base.rebuild_job_id = None
                        if (
                            knowledge_base.rebuild_status
                            == RebuildStatus.BUILDING
                        ):
                            knowledge_base.rebuild_status = (
                                RebuildStatus.FAILED
                            )
            db.commit()
        if not updated:
            logger.error(
                "Job 终态条件更新未生效，租约或状态已变化（job_id=%s）",
                job_id,
            )
            return
        if job is not None:
            JOB_TERMINALS.labels(job.job_type, status.value).inc()
            if job.job_type == JobType.FILE_PROCESS.value:
                FILE_PROCESS_TERMINALS.labels(status.value).inc()
            if job.started_at is not None:
                elapsed = max(
                    0.0, (utc_now() - job.started_at).total_seconds()
                )
                JOB_DURATION.labels(job.job_type).observe(elapsed)
            else:
                elapsed = 0.0
            logger.info(
                (
                    "Job finished job_id=%s job_type=%s status=%s "
                    "duration_seconds=%.3f error_code=%s"
                ),
                job.id,
                job.job_type,
                status.value,
                elapsed,
                error_code,
            )

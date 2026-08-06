"""Bounded, owner-aware SQL aggregates for the product Dashboard."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, TypeVar

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundException
from app.core.logger import get_logger
from app.models import (
    ChatMessage,
    ChatSession,
    FileRecord,
    FileStatus,
    Job,
    JobType,
    KnowledgeBase,
    MessageRole,
    MessageStatus,
    RebuildStatus,
    User,
    UserRole,
)
from app.repositories.session_repository import SessionRepository
from app.schemas.dashboard import (
    DashboardFileStatusCount,
    DashboardMetrics,
    DashboardRecentFile,
    DashboardRecentJob,
    DashboardRecentSession,
    DashboardResponse,
    DashboardRuntimeStatus,
    DashboardTrendPoint,
)
from app.services.runtime_coordinator import RuntimeCoordinator


SectionValue = TypeVar("SectionValue")
logger = get_logger(__name__)


class DashboardService:
    """Build one internally consistent Dashboard snapshot from persisted data."""

    def __init__(
        self,
        db: Session,
        runtime: RuntimeCoordinator,
    ) -> None:
        self.db = db
        self.runtime = runtime

    def get_snapshot(
        self,
        *,
        user: User,
        knowledge_base_id: str | None,
        window_days: int,
        recent_limit: int,
    ) -> DashboardResponse:
        scope_id = self._validate_scope(user, knowledge_base_id)
        now = datetime.now(timezone.utc)
        first_day = now.date() - timedelta(days=window_days - 1)
        since = datetime.combine(first_day, time.min, tzinfo=timezone.utc)
        metrics, file_statuses = self._metrics(user, scope_id)
        section_errors: dict[str, str] = {}
        trend = self._optional_section(
            "trend",
            lambda: self._trend(
                user=user,
                knowledge_base_id=scope_id,
                since=since,
                window_days=window_days,
            ),
            [],
            section_errors,
        )
        recent_files = self._optional_section(
            "recent_files",
            lambda: self._recent_files(user, scope_id, recent_limit),
            [],
            section_errors,
        )
        recent_sessions = self._optional_section(
            "recent_sessions",
            lambda: self._recent_sessions(user, scope_id, recent_limit),
            [],
            section_errors,
        )
        recent_index_jobs = self._optional_section(
            "recent_index_jobs",
            lambda: self._recent_index_jobs(
                user, scope_id, recent_limit
            ),
            [],
            section_errors,
        )
        recent_evaluations = self._optional_section(
            "recent_evaluations",
            lambda: self._recent_evaluations(
                user, scope_id, recent_limit
            ),
            [],
            section_errors,
        )
        effective = self.runtime.effective_settings()
        missing_chat = list(effective.missing_chat_configuration())
        return DashboardResponse(
            generated_at=now,
            window_days=window_days,
            knowledge_base_id=scope_id,
            metrics=metrics,
            trend=trend,
            file_statuses=file_statuses,
            recent_files=recent_files,
            recent_sessions=recent_sessions,
            recent_index_jobs=recent_index_jobs,
            recent_evaluations=recent_evaluations,
            runtime=DashboardRuntimeStatus(
                chat_configured=not missing_chat,
                missing_chat_configuration=missing_chat,
                embedding_key_configured=bool(
                    effective.DASHSCOPE_API_KEY.get_secret_value()
                ),
            ),
            section_errors=section_errors,
        )

    def _optional_section(
        self,
        section: str,
        loader: Callable[[], SectionValue],
        default: SectionValue,
        errors: dict[str, str],
    ) -> SectionValue:
        try:
            return loader()
        except Exception:
            logger.exception("Dashboard section failed: %s", section)
            self.db.rollback()
            errors[section] = "该区域暂时不可用，请刷新后重试"
            return default

    def _validate_scope(
        self,
        user: User,
        knowledge_base_id: str | None,
    ) -> str | None:
        if knowledge_base_id is None:
            return None
        statement = select(KnowledgeBase.id).where(
            KnowledgeBase.id == knowledge_base_id
        )
        if user.role != UserRole.ADMIN.value:
            statement = statement.where(KnowledgeBase.owner_id == user.id)
        if self.db.scalar(statement) is None:
            raise ResourceNotFoundException("知识库不存在")
        return knowledge_base_id

    @staticmethod
    def _kb_filters(
        user: User,
        knowledge_base_id: str | None,
    ) -> list[object]:
        filters: list[object] = []
        if user.role != UserRole.ADMIN.value:
            filters.append(KnowledgeBase.owner_id == user.id)
        if knowledge_base_id is not None:
            filters.append(KnowledgeBase.id == knowledge_base_id)
        return filters

    def _metrics(
        self,
        user: User,
        knowledge_base_id: str | None,
    ) -> tuple[DashboardMetrics, list[DashboardFileStatusCount]]:
        kb_filters = self._kb_filters(user, knowledge_base_id)
        kb_row = self.db.execute(
            select(
                func.count(KnowledgeBase.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                KnowledgeBase.active_collection_name.is_not(
                                    None
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                KnowledgeBase.rebuild_status
                                == RebuildStatus.BUILDING,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(*kb_filters)
        ).one()

        file_row = self.db.execute(
            select(
                func.count(FileRecord.id),
                func.coalesce(func.sum(FileRecord.chunk_count), 0),
                *[
                    func.coalesce(
                        func.sum(
                            case(
                                (FileRecord.status == status, 1),
                                else_=0,
                            )
                        ),
                        0,
                    )
                    for status in FileStatus
                ],
            )
            .select_from(FileRecord)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == FileRecord.knowledge_base_id,
            )
            .where(*kb_filters)
        ).one()
        by_status = {
            status.value: int(file_row[index + 2] or 0)
            for index, status in enumerate(FileStatus)
        }

        session_count = int(
            self.db.scalar(
                select(func.count(ChatSession.id))
                .select_from(ChatSession)
                .join(
                    KnowledgeBase,
                    KnowledgeBase.id == ChatSession.knowledge_base_id,
                )
                .where(*kb_filters)
            )
            or 0
        )
        message_row = self.db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (
                                    ChatMessage.role == MessageRole.USER
                                )
                                & (
                                    ChatMessage.status
                                    == MessageStatus.COMPLETE
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (
                                    ChatMessage.role
                                    == MessageRole.ASSISTANT
                                )
                                & (
                                    ChatMessage.status
                                    == MessageStatus.COMPLETE
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == ChatSession.knowledge_base_id,
            )
            .where(*kb_filters)
        ).one()

        metrics = DashboardMetrics(
            knowledge_bases=int(kb_row[0] or 0),
            files_total=int(file_row[0] or 0),
            files_success=by_status[FileStatus.SUCCESS.value],
            files_in_progress=(
                by_status[FileStatus.PENDING.value]
                + by_status[FileStatus.PROCESSING.value]
            ),
            files_failed=by_status[FileStatus.FAILED.value],
            chunks=int(file_row[1] or 0),
            sessions=session_count,
            user_questions=int(message_row[0] or 0),
            assistant_answers=int(message_row[1] or 0),
            active_indexes=int(kb_row[1] or 0),
            building_indexes=int(kb_row[2] or 0),
        )
        file_statuses = [
            DashboardFileStatusCount(
                status=status.value,
                count=by_status[status.value],
            )
            for status in FileStatus
        ]
        return metrics, file_statuses

    def _trend(
        self,
        *,
        user: User,
        knowledge_base_id: str | None,
        since: datetime,
        window_days: int,
    ) -> list[DashboardTrendPoint]:
        kb_filters = self._kb_filters(user, knowledge_base_id)
        uploads = self._daily_counts(
            select(
                func.date(FileRecord.created_at),
                func.count(FileRecord.id),
            )
            .select_from(FileRecord)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == FileRecord.knowledge_base_id,
            )
            .where(FileRecord.created_at >= since, *kb_filters)
            .group_by(func.date(FileRecord.created_at))
        )
        questions = self._daily_counts(
            select(
                func.date(ChatMessage.created_at),
                func.count(ChatMessage.id),
            )
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == ChatSession.knowledge_base_id,
            )
            .where(
                ChatMessage.created_at >= since,
                ChatMessage.role == MessageRole.USER,
                ChatMessage.status == MessageStatus.COMPLETE,
                *kb_filters,
            )
            .group_by(func.date(ChatMessage.created_at))
        )
        failed_files = self._daily_counts(
            select(
                func.date(FileRecord.updated_at),
                func.count(FileRecord.id),
            )
            .select_from(FileRecord)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == FileRecord.knowledge_base_id,
            )
            .where(
                FileRecord.updated_at >= since,
                FileRecord.status == FileStatus.FAILED,
                *kb_filters,
            )
            .group_by(func.date(FileRecord.updated_at))
        )
        index_operations = self._daily_counts(
            self._index_job_scope(user, knowledge_base_id)
            .with_only_columns(
                func.date(Job.created_at),
                func.count(Job.id),
                maintain_column_froms=True,
            )
            .where(Job.created_at >= since)
            .group_by(func.date(Job.created_at))
        )
        evaluation_runs = self._daily_counts(
            self._evaluation_job_scope(user, knowledge_base_id)
            .with_only_columns(
                func.date(Job.created_at),
                func.count(Job.id),
                maintain_column_froms=True,
            )
            .where(Job.created_at >= since)
            .group_by(func.date(Job.created_at))
        )
        first_day = since.date()
        return [
            DashboardTrendPoint(
                date=current,
                uploads=uploads.get(current, 0),
                questions=questions.get(current, 0),
                failed_files=failed_files.get(current, 0),
                index_operations=index_operations.get(current, 0),
                evaluation_runs=evaluation_runs.get(current, 0),
            )
            for current in (
                first_day + timedelta(days=offset)
                for offset in range(window_days)
            )
        ]

    def _daily_counts(self, statement: object) -> dict[date, int]:
        counts: dict[date, int] = {}
        for raw_day, count in self.db.execute(statement):
            try:
                resolved = date.fromisoformat(str(raw_day))
            except (TypeError, ValueError):
                continue
            counts[resolved] = int(count or 0)
        return counts

    def _recent_files(
        self,
        user: User,
        knowledge_base_id: str | None,
        limit: int,
    ) -> list[DashboardRecentFile]:
        rows = self.db.execute(
            select(FileRecord, KnowledgeBase.name)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == FileRecord.knowledge_base_id,
            )
            .where(*self._kb_filters(user, knowledge_base_id))
            .order_by(FileRecord.updated_at.desc(), FileRecord.id.desc())
            .limit(limit)
        )
        return [
            DashboardRecentFile(
                id=record.id,
                knowledge_base_id=record.knowledge_base_id,
                knowledge_base_name=knowledge_base_name,
                file_name=record.original_name,
                file_type=record.file_type,
                status=(
                    record.status.value
                    if hasattr(record.status, "value")
                    else str(record.status)
                ),
                chunk_count=record.chunk_count,
                updated_at=record.updated_at,
            )
            for record, knowledge_base_name in rows
        ]

    def _recent_sessions(
        self,
        user: User,
        knowledge_base_id: str | None,
        limit: int,
    ) -> list[DashboardRecentSession]:
        owner_id = (
            None if user.role == UserRole.ADMIN.value else str(user.id)
        )
        summaries = SessionRepository(self.db).list_sessions(
            knowledge_base_id=knowledge_base_id,
            owner_id=owner_id,
            limit=limit,
            offset=0,
        )
        names = self._knowledge_base_names(
            item.knowledge_base_id for item in summaries
        )
        return [
            DashboardRecentSession(
                id=item.id,
                knowledge_base_id=item.knowledge_base_id,
                knowledge_base_name=names.get(
                    item.knowledge_base_id, "已删除知识库"
                ),
                title=item.title,
                preview=item.preview,
                message_count=item.message_count,
                updated_at=item.updated_at,
            )
            for item in summaries
        ]

    def _index_job_scope(
        self,
        user: User,
        knowledge_base_id: str | None,
    ):
        return (
            select(Job)
            .join(KnowledgeBase, KnowledgeBase.id == Job.resource_id)
            .where(
                Job.job_type.in_(
                    (
                        JobType.KB_REBUILD.value,
                        JobType.KB_CLEANUP_RETIRED.value,
                    )
                ),
                *self._kb_filters(user, knowledge_base_id),
            )
        )

    def _evaluation_job_scope(
        self,
        user: User,
        knowledge_base_id: str | None,
    ):
        statement = select(Job).where(
            Job.job_type == JobType.RAG_EVALUATION.value
        )
        if user.role != UserRole.ADMIN.value:
            statement = statement.where(Job.created_by_id == user.id)
        if knowledge_base_id is not None:
            statement = statement.where(
                Job.resource_id == knowledge_base_id
            )
        return statement

    def _recent_index_jobs(
        self,
        user: User,
        knowledge_base_id: str | None,
        limit: int,
    ) -> list[DashboardRecentJob]:
        jobs = list(
            self.db.scalars(
                self._index_job_scope(user, knowledge_base_id)
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(limit)
            ).all()
        )
        return [self._job_response(job) for job in jobs]

    def _recent_evaluations(
        self,
        user: User,
        knowledge_base_id: str | None,
        limit: int,
    ) -> list[DashboardRecentJob]:
        jobs = list(
            self.db.scalars(
                self._evaluation_job_scope(user, knowledge_base_id)
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(limit)
            ).all()
        )
        return [self._job_response(job) for job in jobs]

    @staticmethod
    def _job_response(job: Job) -> DashboardRecentJob:
        return DashboardRecentJob(
            id=job.id,
            knowledge_base_id=job.resource_id,
            knowledge_base_name=(
                job.resource_name_snapshot or "已删除知识库"
            ),
            job_type=job.job_type,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            error_message=job.error_message,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )

    def _knowledge_base_names(
        self, knowledge_base_ids: Iterable[str]
    ) -> dict[str, str]:
        ids = set(knowledge_base_ids)
        if not ids:
            return {}
        return dict(
            self.db.execute(
                select(KnowledgeBase.id, KnowledgeBase.name).where(
                    KnowledgeBase.id.in_(ids)
                )
            ).all()
        )

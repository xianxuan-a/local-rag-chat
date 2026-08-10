"""Synchronous versioned Collection rebuild and pointer maintenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    AppException,
    ConflictException,
    FileProcessException,
    ResourceNotFoundException,
    VectorStoreException,
)
from app.core.logger import get_logger
from app.models import FileRecord, Job, RebuildStatus
from app.repositories.file_repository import FileRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.job_repository import JobRepository
from app.schemas.rebuild import (
    CollectionMaintenanceResponse,
    RebuildFailure,
    RebuildResponse,
)
from app.services.document_loader import DocumentLoaderService
from app.services.document_splitter import DocumentSplitterService
from app.services.file_service import FileService
from app.services.runtime_coordinator import RuntimeCoordinator


logger = get_logger(__name__)


class KnowledgeBaseRebuildService:
    """Build candidate Collections and atomically switch database pointers."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        runtime: RuntimeCoordinator,
    ) -> None:
        self.db = db
        self.settings = settings
        self.runtime = runtime
        self.knowledge_bases = KnowledgeBaseRepository(db)
        self.files = FileRepository(db)
        self.loader = DocumentLoaderService()
        self.splitter = DocumentSplitterService(settings=settings)
        self.file_service = FileService(db, settings, runtime)

    def rebuild(
        self,
        knowledge_base_id: str,
        *,
        job_id: str | None = None,
        checkpoint: object | None = None,
    ) -> RebuildResponse:
        with self.runtime.admin_operation("rebuild_knowledge_base"):
            return self._rebuild_locked(
                knowledge_base_id, job_id=job_id, checkpoint=checkpoint
            )

    def _rebuild_locked(
        self,
        knowledge_base_id: str,
        *,
        job_id: str | None = None,
        checkpoint: object | None = None,
    ) -> RebuildResponse:
        knowledge_base = self._get_knowledge_base(knowledge_base_id)
        self._validate_distinct_pointers(knowledge_base)
        if knowledge_base.rebuild_status is RebuildStatus.BUILDING:
            raise ConflictException(
                "知识库已有正在构建的候选 Collection",
                data=self._building_context(knowledge_base),
            )
        if self.files.has_processing(knowledge_base.id):
            raise ConflictException("知识库存在 PROCESSING 文件，不能开始重建")

        if knowledge_base.cleanup_collection_name:
            self._cleanup_retired_locked(knowledge_base.id)
            self.db.expire_all()
            knowledge_base = self._get_knowledge_base(knowledge_base.id)

        if knowledge_base.building_collection_name:
            self._cleanup_failed_building_locked(knowledge_base)
            self.db.expire_all()
            knowledge_base = self._get_knowledge_base(knowledge_base.id)

        file_records = self.files.list_by_knowledge_base(knowledge_base.id)
        config = self.runtime.vector_store.current_config
        collection_name, generation = (
            self.runtime.vector_store.generate_collection_name(
                knowledge_base.id,
                config.config_hash,
            )
        )
        run_id = str(uuid4())
        started_at = datetime.now(timezone.utc)
        source_collection = knowledge_base.active_collection_name
        source_previous = knowledge_base.previous_collection_name

        knowledge_base.building_collection_name = collection_name
        knowledge_base.building_embedding_config_hash = config.config_hash
        knowledge_base.rebuild_status = RebuildStatus.BUILDING
        knowledge_base.rebuild_run_id = run_id
        knowledge_base.rebuild_job_id = job_id
        knowledge_base.building_started_at = started_at
        if job_id:
            job = self.db.get(Job, job_id)
            if job is not None:
                job.collection_name = collection_name
                job.embedding_config_hash = config.config_hash
                job.payload = {
                    **dict(job.payload),
                    "source_collection": source_collection,
                    "source_previous": source_previous,
                    "rebuild_run_id": run_id,
                }
        self.db.commit()
        if checkpoint is not None:
            checkpoint("REBUILD_CANDIDATE_CLAIMED", 10, force=True)

        try:
            self.runtime.vector_store.create_collection(
                name=collection_name,
                knowledge_base_id=knowledge_base.id,
                config=config,
                generation=generation,
                lifecycle_status="BUILDING",
            )
        except Exception:
            self._persist_rebuild_failure(knowledge_base.id, collection_name)
            raise
        if checkpoint is not None:
            checkpoint("REBUILD_COLLECTION_CREATED", 20, force=True)

        failures: list[RebuildFailure] = []
        expected_counts: dict[str, int] = {}
        for file_record in file_records:
            try:
                chunks = self._prepare_file_chunks(file_record)
                embeddings = self.runtime.vector_store.embed_documents(
                    chunks, config
                )
                self.runtime.vector_store.replace_file_documents(
                    collection_name=collection_name,
                    knowledge_base_id=knowledge_base.id,
                    file_id=file_record.id,
                    documents=chunks,
                    embeddings=embeddings,
                    config=config,
                    role="building",
                    processing_job_id=job_id,
                    vector_run_id=run_id,
                    expected_chunk_count=len(chunks),
                )
                expected_counts[file_record.id] = len(chunks)
                if checkpoint is not None and file_records:
                    completed = len(expected_counts) + len(failures)
                    checkpoint(
                        "REBUILD_FILES",
                        20 + int(55 * completed / len(file_records)),
                    )
            except Exception as exc:
                failures.append(
                    RebuildFailure(
                        file_id=UUID(file_record.id),
                        file_name=file_record.original_name,
                        error=self._safe_error(exc),
                    )
                )
                try:
                    snapshot = self.runtime.vector_store.snapshot_file(
                        collection_name,
                        knowledge_base_id=knowledge_base.id,
                        file_id=file_record.id,
                        expected_config_hash=config.config_hash,
                    )
                    self.runtime.vector_store.delete_ids(
                        collection_name, snapshot.ids
                    )
                except Exception:
                    logger.critical(
                        "无法清理失败文件的候选向量（kb_id=%s, file_id=%s）",
                        knowledge_base.id,
                        file_record.id,
                        exc_info=True,
                    )

        if failures:
            self._persist_rebuild_failure(knowledge_base.id, collection_name)
            succeeded = len(file_records) - len(failures)
            return RebuildResponse(
                status="PARTIAL_SUCCESS" if succeeded else "FAILED",
                knowledge_base_id=UUID(knowledge_base.id),
                total=len(file_records),
                succeeded=succeeded,
                failed=len(failures),
                failures=failures,
                source_collection=source_collection,
                target_collection=collection_name,
                embedding_config_hash=config.config_hash,
                generation=generation,
                switched=False,
            )

        try:
            self.runtime.vector_store.validate_whole_collection(
                name=collection_name,
                knowledge_base_id=knowledge_base.id,
                config_hash=config.config_hash,
                expected_file_ids={record.id for record in file_records},
                expected_counts=expected_counts,
            )
        except Exception:
            self._persist_rebuild_failure(knowledge_base.id, collection_name)
            raise
        if checkpoint is not None:
            checkpoint("REBUILD_CANDIDATE_VERIFIED", 80, force=True)

        self.db.expire_all()
        current_kb = self._get_knowledge_base(knowledge_base.id)
        if (
            current_kb.rebuild_status is not RebuildStatus.BUILDING
            or current_kb.rebuild_run_id != run_id
            or current_kb.building_collection_name != collection_name
            or current_kb.active_collection_name != source_collection
            or current_kb.previous_collection_name != source_previous
        ):
            self._persist_rebuild_failure(knowledge_base.id, collection_name)
            raise ConflictException("重建指针在候选构建期间发生变化")

        indexed_at = datetime.now(timezone.utc)
        try:
            current_kb.cleanup_collection_name = (
                current_kb.previous_collection_name
            )
            current_kb.previous_collection_name = (
                current_kb.active_collection_name
            )
            current_kb.previous_embedding_config_hash = (
                current_kb.active_embedding_config_hash
            )
            current_kb.active_collection_name = collection_name
            current_kb.active_embedding_config_hash = config.config_hash
            current_kb.building_collection_name = None
            current_kb.building_embedding_config_hash = None
            current_kb.rebuild_status = RebuildStatus.IDLE
            current_kb.rebuild_run_id = None
            current_kb.rebuild_job_id = None
            current_kb.building_started_at = None
            for record in file_records:
                current_record = self.files.get_by_id(record.id)
                if current_record is None:
                    raise ConflictException("重建文件集合发生变化")
                self.files.update_active_index(
                    current_record,
                    chunk_count=expected_counts[record.id],
                    config_hash=config.config_hash,
                    indexed_at=indexed_at,
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            self._persist_rebuild_failure(knowledge_base.id, collection_name)
            raise

        try:
            self.runtime.vector_store.set_lifecycle(collection_name, "ACTIVE")
            if source_collection:
                self.runtime.vector_store.set_lifecycle(
                    source_collection, "RETIRED"
                )
        except Exception:
            logger.critical(
                "数据库已切换但 Collection lifecycle 更新失败（kb_id=%s）",
                knowledge_base.id,
                exc_info=True,
            )

        cleanup_pending = False
        self.db.expire_all()
        current_kb = self._get_knowledge_base(knowledge_base.id)
        if current_kb.cleanup_collection_name:
            try:
                self._cleanup_retired_locked(knowledge_base.id)
            except Exception:
                cleanup_pending = True
                logger.error(
                    "重建切换成功，但旧 Collection 延迟清理失败（kb_id=%s）",
                    knowledge_base.id,
                    exc_info=True,
                )

        return RebuildResponse(
            status="SUCCESS",
            knowledge_base_id=UUID(knowledge_base.id),
            total=len(file_records),
            succeeded=len(file_records),
            failed=0,
            failures=[],
            source_collection=source_collection,
            target_collection=collection_name,
            embedding_config_hash=config.config_hash,
            generation=generation,
            switched=True,
            cleanup_pending=cleanup_pending,
        )

    def cleanup_retired(
        self, knowledge_base_id: str
    ) -> CollectionMaintenanceResponse:
        with self.runtime.admin_operation("cleanup_retired"):
            return self._cleanup_retired_locked(knowledge_base_id)

    def cleanup_indexes(
        self,
        knowledge_base_id: str,
        *,
        cleanup_previous: bool,
        cleanup_orphans: bool,
    ) -> dict[str, Any]:
        """Delete only server-resolved, revalidated safe Collection targets."""

        with self.runtime.admin_operation("cleanup_indexes"):
            with self.runtime.vector_write_lock:
                deleted: list[str] = []
                skipped: list[dict[str, str]] = []
                cleanup = self._cleanup_retired_locked(knowledge_base_id)
                if cleanup.collection_name is not None:
                    deleted.append(cleanup.collection_name)
                knowledge_base = self._get_knowledge_base(
                    knowledge_base_id
                )
                self._validate_distinct_pointers(knowledge_base)
                jobs = JobRepository(self.db)

                if cleanup_previous and knowledge_base.previous_collection_name:
                    previous = knowledge_base.previous_collection_name
                    if jobs.collection_is_pinned(previous):
                        skipped.append(
                            {
                                "collection_name": previous,
                                "reason": "Previous Collection 正被评估 Job pin",
                            }
                        )
                    elif not self.runtime.vector_store.collection_exists(
                        previous
                    ):
                        if not self.knowledge_bases.clear_previous_if_matches(
                            knowledge_base.id, previous
                        ):
                            raise ConflictException(
                                "Previous 指针已发生变化"
                            )
                        self.db.commit()
                        deleted.append(previous)
                    else:
                        self.runtime.vector_store.get_collection(
                            previous,
                            knowledge_base_id=knowledge_base.id,
                            expected_config_hash=(
                                knowledge_base.previous_embedding_config_hash
                            ),
                            role="previous",
                            for_write=False,
                        )
                        self.runtime.vector_store.delete_collection(previous)
                        if not self.knowledge_bases.clear_previous_if_matches(
                            knowledge_base.id, previous
                        ):
                            self.db.rollback()
                            raise VectorStoreException(
                                "Previous Collection 已删除但指针清理失败"
                            )
                        self.db.commit()
                        deleted.append(previous)

                if cleanup_orphans:
                    self.db.expire_all()
                    knowledge_base = self._get_knowledge_base(
                        knowledge_base_id
                    )
                    referenced = {
                        knowledge_base.active_collection_name,
                        knowledge_base.previous_collection_name,
                        knowledge_base.building_collection_name,
                        knowledge_base.cleanup_collection_name,
                    }
                    for collection in self.runtime.vector_store.list_collections():
                        name = str(collection.name)
                        metadata = getattr(collection, "metadata", None)
                        if (
                            name in referenced
                            or not isinstance(metadata, dict)
                            or str(metadata.get("knowledge_base_id"))
                            != str(knowledge_base.id)
                        ):
                            continue
                        lifecycle = metadata.get("lifecycle_status")
                        if lifecycle not in {"RETIRED", "FAILED"}:
                            skipped.append(
                                {
                                    "collection_name": name,
                                    "reason": (
                                        "孤立 Collection lifecycle "
                                        "不允许自动清理"
                                    ),
                                }
                            )
                            continue
                        if jobs.collection_is_referenced_by_nonterminal_job(
                            name
                        ):
                            skipped.append(
                                {
                                    "collection_name": name,
                                    "reason": "Collection 正被非终态 Job 引用",
                                }
                            )
                            continue
                        try:
                            self.runtime.vector_store.validate_collection(
                                collection,
                                knowledge_base_id=knowledge_base.id,
                            )
                        except Exception as exc:
                            skipped.append(
                                {
                                    "collection_name": name,
                                    "reason": str(exc),
                                }
                            )
                            continue
                        self.runtime.vector_store.delete_collection(name)
                        deleted.append(name)
                return {
                    "status": "SUCCESS" if deleted else "NOOP",
                    "knowledge_base_id": knowledge_base.id,
                    "deleted": deleted,
                    "skipped": skipped,
                }

    def _cleanup_retired_locked(
        self, knowledge_base_id: str
    ) -> CollectionMaintenanceResponse:
        knowledge_base = self._get_knowledge_base(knowledge_base_id)
        self._validate_distinct_pointers(knowledge_base)
        name = knowledge_base.cleanup_collection_name
        if not name:
            return CollectionMaintenanceResponse(
                status="NOOP",
                knowledge_base_id=UUID(knowledge_base.id),
            )
        if JobRepository(self.db).collection_is_pinned(name):
            raise ConflictException(
                "Cleanup Collection 正被非终态评估 Job pin，延迟清理"
            )
        if name in {
            knowledge_base.active_collection_name,
            knowledge_base.previous_collection_name,
            knowledge_base.building_collection_name,
        }:
            raise ConflictException("Cleanup Collection 仍被其他指针引用")
        if not self.runtime.vector_store.collection_exists(name):
            if not self.knowledge_bases.clear_cleanup_if_matches(
                knowledge_base.id, name
            ):
                raise ConflictException("Cleanup 指针已发生变化")
            self.db.commit()
            return CollectionMaintenanceResponse(
                status="SUCCESS",
                knowledge_base_id=UUID(knowledge_base.id),
                collection_name=name,
                already_missing=True,
            )
        self.runtime.vector_store.get_collection(
            name,
            knowledge_base_id=knowledge_base.id,
            role="cleanup",
            for_write=False,
        )
        self.runtime.vector_store.delete_collection(name)
        if not self.knowledge_bases.clear_cleanup_if_matches(
            knowledge_base.id, name
        ):
            self.db.rollback()
            raise VectorStoreException(
                "Collection 已删除但 cleanup 指针清理失败"
            )
        self.db.commit()
        return CollectionMaintenanceResponse(
            status="SUCCESS",
            knowledge_base_id=UUID(knowledge_base.id),
            collection_name=name,
        )

    def abort_building(
        self, knowledge_base_id: str
    ) -> CollectionMaintenanceResponse:
        with self.runtime.admin_operation("abort_building"):
            jobs = JobRepository(self.db)
            if jobs.has_nonterminal_knowledge_base_job(
                knowledge_base_id
            ) or jobs.has_nonterminal_file_job_for_knowledge_base(
                knowledge_base_id
            ):
                raise ConflictException(
                    "知识库或文件维护 Job 尚未终态，不能 abort-building"
                )
            knowledge_base = self._get_knowledge_base(knowledge_base_id)
            self._validate_distinct_pointers(knowledge_base)
            name = knowledge_base.building_collection_name
            if not name:
                return CollectionMaintenanceResponse(
                    status="NOOP",
                    knowledge_base_id=UUID(knowledge_base.id),
                )
            if name in {
                knowledge_base.active_collection_name,
                knowledge_base.previous_collection_name,
                knowledge_base.cleanup_collection_name,
            }:
                raise ConflictException(
                    "Building Collection 仍被其他指针引用"
                )
            already_missing = not self.runtime.vector_store.collection_exists(name)
            if not already_missing:
                collection = self.runtime.vector_store.get_collection(
                    name,
                    knowledge_base_id=knowledge_base.id,
                    expected_config_hash=(
                        knowledge_base.building_embedding_config_hash
                    ),
                    role="building",
                    for_write=False,
                )
                if collection.metadata.get("lifecycle_status") == "BUILDING":
                    self.runtime.vector_store.set_lifecycle(name, "FAILED")
                self.runtime.vector_store.delete_collection(name)
            if not self.knowledge_bases.clear_building_if_matches(
                knowledge_base.id, name
            ):
                self.db.rollback()
                raise ConflictException("Building 指针已发生变化")
            self.db.commit()
            return CollectionMaintenanceResponse(
                status="SUCCESS",
                knowledge_base_id=UUID(knowledge_base.id),
                collection_name=name,
                already_missing=already_missing,
            )

    def rollback(
        self, knowledge_base_id: str
    ) -> CollectionMaintenanceResponse:
        with self.runtime.admin_operation("rollback_collection"):
            with self.runtime.vector_write_lock:
                return self._rollback_locked(knowledge_base_id)

    def _rollback_locked(
        self, knowledge_base_id: str
    ) -> CollectionMaintenanceResponse:
        knowledge_base = self._get_knowledge_base(knowledge_base_id)
        self._validate_distinct_pointers(knowledge_base)
        jobs = JobRepository(self.db)
        if jobs.has_nonterminal_knowledge_base_job(
            knowledge_base.id
        ) or jobs.has_nonterminal_file_job_for_knowledge_base(
            knowledge_base.id
        ):
            raise ConflictException(
                "知识库或文件维护 Job 尚未终态，不能回滚"
            )
        if knowledge_base.rebuild_status is RebuildStatus.BUILDING:
            raise ConflictException("知识库正在重建，不能回滚")
        if self.files.has_processing(knowledge_base.id):
            raise ConflictException("知识库存在 PROCESSING 文件，不能回滚")
        previous = knowledge_base.previous_collection_name
        if not previous:
            return CollectionMaintenanceResponse(
                status="NOOP",
                knowledge_base_id=UUID(knowledge_base.id),
            )
        if jobs.collection_is_pinned(previous):
            raise ConflictException(
                "Previous Collection 正被评估 Job pin，不能切换为写入目标"
            )
        collection = self.runtime.vector_store.get_collection(
            previous,
            knowledge_base_id=knowledge_base.id,
            expected_config_hash=(
                knowledge_base.previous_embedding_config_hash
            ),
            role="previous",
            for_write=False,
        )
        counts = self.runtime.vector_store.collection_file_counts(previous)
        old_active = knowledge_base.active_collection_name
        old_active_hash = knowledge_base.active_embedding_config_hash
        previous_hash = knowledge_base.previous_embedding_config_hash
        knowledge_base.active_collection_name = previous
        knowledge_base.active_embedding_config_hash = previous_hash
        knowledge_base.previous_collection_name = old_active
        knowledge_base.previous_embedding_config_hash = old_active_hash
        for record in self.files.list_by_knowledge_base(knowledge_base.id):
            count = counts.get(record.id, 0)
            record.chunk_count = count
            record.has_active_vectors = count > 0
            record.active_index_config_hash = previous_hash if count else None
        self.db.commit()
        try:
            self.runtime.vector_store.set_lifecycle(previous, "ACTIVE")
            if old_active:
                self.runtime.vector_store.set_lifecycle(
                    old_active, "RETIRED"
                )
        except Exception:
            logger.critical(
                "回滚指针已提交但 lifecycle 更新失败（kb_id=%s）",
                knowledge_base.id,
                exc_info=True,
            )
        return CollectionMaintenanceResponse(
            status="SUCCESS",
            knowledge_base_id=UUID(knowledge_base.id),
            collection_name=collection.name,
        )

    def _cleanup_failed_building_locked(self, knowledge_base: object) -> None:
        name = knowledge_base.building_collection_name
        if not name:
            return
        if name in {
            knowledge_base.active_collection_name,
            knowledge_base.previous_collection_name,
            knowledge_base.cleanup_collection_name,
        }:
            raise ConflictException("Building Collection 指针冲突")
        if not self.runtime.vector_store.collection_exists(name):
            if not self.knowledge_bases.clear_building_if_matches(
                knowledge_base.id, name
            ):
                raise ConflictException("Building 指针已发生变化")
            self.db.commit()
            return
        collection = self.runtime.vector_store.get_collection(
            name,
            knowledge_base_id=knowledge_base.id,
            expected_config_hash=knowledge_base.building_embedding_config_hash,
            role="building",
            for_write=False,
        )
        if collection.metadata.get("lifecycle_status") != "FAILED":
            raise ConflictException(
                "知识库存在未完成的 BUILDING 候选，请先 abort-building"
            )
        self.runtime.vector_store.delete_collection(name)
        if not self.knowledge_bases.clear_building_if_matches(
            knowledge_base.id, name
        ):
            raise ConflictException("Building 指针已发生变化")
        self.db.commit()

    def _prepare_file_chunks(self, file_record: FileRecord) -> list:
        path = self.file_service._resolve_managed_file_path(file_record)
        if not path.exists():
            raise FileProcessException("重建源文件不存在")
        documents = self.loader.load_file(
            path,
            file_id=file_record.id,
            knowledge_base_id=file_record.knowledge_base_id,
            file_name=file_record.original_name,
            file_type=file_record.file_type,
        )
        return self.splitter.split_documents(documents)

    def _persist_rebuild_failure(
        self,
        knowledge_base_id: str,
        collection_name: str,
    ) -> None:
        try:
            self.runtime.vector_store.set_lifecycle(
                collection_name, "FAILED"
            )
        except Exception:
            logger.critical(
                "无法标记候选 Collection 为 FAILED（kb_id=%s, collection=%s）",
                knowledge_base_id,
                collection_name,
                exc_info=True,
            )
        try:
            self.db.rollback()
            knowledge_base = self.knowledge_bases.get_by_id(knowledge_base_id)
            if (
                knowledge_base is not None
                and knowledge_base.building_collection_name == collection_name
            ):
                knowledge_base.rebuild_status = RebuildStatus.FAILED
                self.db.commit()
        except Exception:
            self.db.rollback()
            logger.critical(
                "无法持久化知识库重建失败状态（kb_id=%s）",
                knowledge_base_id,
                exc_info=True,
            )

    def _get_knowledge_base(self, knowledge_base_id: str):
        knowledge_base = self.knowledge_bases.get_by_id(knowledge_base_id)
        if knowledge_base is None:
            raise ResourceNotFoundException("知识库不存在")
        return knowledge_base

    @staticmethod
    def _validate_distinct_pointers(knowledge_base: object) -> None:
        names = [
            name
            for name in (
                knowledge_base.active_collection_name,
                knowledge_base.previous_collection_name,
                knowledge_base.building_collection_name,
                knowledge_base.cleanup_collection_name,
            )
            if name
        ]
        if len(names) != len(set(names)):
            raise ConflictException("知识库 Collection 指针存在重复引用")

    @staticmethod
    def _building_context(knowledge_base: object) -> dict[str, str | None]:
        return {
            "building_collection_name": knowledge_base.building_collection_name,
            "rebuild_run_id": knowledge_base.rebuild_run_id,
            "building_started_at": (
                knowledge_base.building_started_at.isoformat()
                if knowledge_base.building_started_at
                else None
            ),
        }

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, AppException):
            return exc.message[:1000]
        return "文件重建失败，请查看服务日志"

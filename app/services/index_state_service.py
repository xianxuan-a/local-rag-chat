"""Read-only index state projection over SQL pointers, Jobs, and Chroma."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobType, KnowledgeBase, UserRole
from app.repositories.job_repository import JobRepository
from app.schemas.index import IndexCollectionResponse, IndexStateResponse
from app.schemas.job import JobResponse
from app.services.runtime_coordinator import RuntimeCoordinator


class IndexStateService:
    def __init__(self, db: Session, runtime: RuntimeCoordinator) -> None:
        self.db = db
        self.runtime = runtime
        self.jobs = JobRepository(db)

    def list_states(
        self,
        *,
        user: object,
        knowledge_base_id: str | None = None,
    ) -> list[IndexStateResponse]:
        statement = select(KnowledgeBase)
        if user.role != UserRole.ADMIN.value:
            statement = statement.where(KnowledgeBase.owner_id == user.id)
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeBase.id == knowledge_base_id)
        knowledge_bases = list(
            self.db.scalars(
                statement.order_by(
                    KnowledgeBase.updated_at.desc(),
                    KnowledgeBase.id.desc(),
                )
            ).all()
        )
        all_collections = self.runtime.vector_store.list_collections()
        by_name = {
            str(collection.name): collection for collection in all_collections
        }
        return [
            self._state(knowledge_base, by_name)
            for knowledge_base in knowledge_bases
        ]

    def _state(
        self,
        knowledge_base: KnowledgeBase,
        by_name: dict[str, object],
    ) -> IndexStateResponse:
        pointers = {
            "active": knowledge_base.active_collection_name,
            "previous": knowledge_base.previous_collection_name,
            "building": knowledge_base.building_collection_name,
            "cleanup": knowledge_base.cleanup_collection_name,
        }
        referenced = {name for name in pointers.values() if name}
        collections = [
            self._collection(
                knowledge_base,
                role,
                name,
                by_name.get(name),
            )
            for role, name in pointers.items()
            if name
        ]
        for name, collection in sorted(by_name.items()):
            metadata = getattr(collection, "metadata", None)
            if (
                name not in referenced
                and isinstance(metadata, dict)
                and str(metadata.get("knowledge_base_id"))
                == str(knowledge_base.id)
            ):
                collections.append(
                    self._collection(
                        knowledge_base,
                        "orphan",
                        name,
                        collection,
                    )
                )
        latest = self.db.scalar(
            select(Job)
            .where(
                Job.resource_type == "KNOWLEDGE_BASE",
                Job.resource_id == knowledge_base.id,
                Job.job_type.in_(
                    (
                        JobType.KB_REBUILD.value,
                        JobType.KB_CLEANUP_RETIRED.value,
                    )
                ),
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        return IndexStateResponse(
            knowledge_base_id=knowledge_base.id,
            knowledge_base_name=knowledge_base.name,
            rebuild_status=(
                knowledge_base.rebuild_status.value
                if hasattr(knowledge_base.rebuild_status, "value")
                else str(knowledge_base.rebuild_status)
            ),
            rebuild_run_id=knowledge_base.rebuild_run_id,
            building_started_at=knowledge_base.building_started_at,
            collections=collections,
            latest_job=(
                JobResponse.model_validate(latest) if latest is not None else None
            ),
        )

    def _collection(
        self,
        knowledge_base: KnowledgeBase,
        role: str,
        name: str,
        collection: object | None,
    ) -> IndexCollectionResponse:
        if collection is None:
            return IndexCollectionResponse(
                collection_name=name,
                role=role,
                exists=False,
                cleanup_reason="数据库指针引用的 Collection 不存在",
                error="COLLECTION_MISSING",
            )
        metadata = getattr(collection, "metadata", None)
        try:
            self.runtime.vector_store.validate_collection(
                collection,
                knowledge_base_id=knowledge_base.id,
            )
            rows = collection.get(include=["metadatas"])
            metadatas = rows.get("metadatas") or []
            file_counts = Counter(
                str(item.get("file_id"))
                for item in metadatas
                if isinstance(item, dict) and item.get("file_id")
            )
            error = None
        except Exception as exc:
            metadatas = []
            file_counts = Counter()
            error = str(exc)
        metadata = metadata if isinstance(metadata, dict) else {}
        lifecycle = metadata.get("lifecycle_status")
        safe, reason = self._cleanup_safety(role, lifecycle, error)
        if (
            safe
            and self.jobs.collection_is_referenced_by_nonterminal_job(name)
        ):
            safe = False
            reason = "Collection 正被非终态 Job 引用"
        return IndexCollectionResponse(
            collection_name=name,
            role=role,
            exists=True,
            lifecycle_status=(
                str(lifecycle) if lifecycle is not None else None
            ),
            generation=(
                str(metadata.get("generation"))
                if metadata.get("generation") is not None
                else None
            ),
            embedding_provider=metadata.get("embedding_provider"),
            embedding_model=metadata.get("embedding_model"),
            embedding_dimension=metadata.get("embedding_dimension"),
            distance_metric=metadata.get("distance_metric"),
            embedding_config_hash=metadata.get("embedding_config_hash"),
            file_count=len(file_counts) if error is None else None,
            chunk_count=len(metadatas) if error is None else None,
            safe_to_cleanup=safe,
            cleanup_reason=reason,
            error=error,
        )

    @staticmethod
    def _cleanup_safety(
        role: str,
        lifecycle: object,
        error: str | None,
    ) -> tuple[bool, str]:
        if error is not None:
            return False, "Collection 元数据或配置无法验证"
        if role == "active":
            return False, "活动索引禁止清理"
        if role == "building":
            return False, "请先取消 Job 并使用 abort-building"
        if role == "previous":
            return True, "清理后将失去当前回滚版本"
        if role in {"cleanup", "orphan"} and lifecycle in {
            "RETIRED",
            "FAILED",
        }:
            return True, "后端将在执行前重新验证引用和 Job pin"
        return False, "Collection lifecycle 不允许自动清理"

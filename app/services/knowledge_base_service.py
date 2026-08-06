"""Knowledge-base business operations and transaction boundaries."""

from contextlib import nullcontext
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictException, ResourceNotFoundException
from app.models.knowledge_base import KnowledgeBase, RebuildStatus
from app.repositories.file_repository import FileRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.job_repository import JobRepository
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.runtime_coordinator import RuntimeCoordinator
from app.services.vector_store_service import CollectionSnapshot

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Provide real CRUD behavior for knowledge bases."""

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        runtime: RuntimeCoordinator | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.runtime = runtime
        self.repository = KnowledgeBaseRepository(db)
        self.files = FileRepository(db)
        self.jobs = JobRepository(db)

    def create_knowledge_base(
        self, payload: KnowledgeBaseCreate, owner_id: str
    ) -> KnowledgeBase:
        """Create and commit one knowledge base."""
        try:
            knowledge_base = self.repository.create(
                name=payload.name,
                description=payload.description,
                owner_id=owner_id,
                web_access_policy=payload.web_access_policy,
            )
            self.db.commit()
            return knowledge_base
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictException("同名知识库已存在") from exc
        except Exception:
            self.db.rollback()
            raise

    def list_knowledge_bases(self, owner_id: str | None = None) -> list[KnowledgeBase]:
        """Return all knowledge bases in repository-defined order."""
        return self.repository.list_all(owner_id)

    def update_knowledge_base(
        self,
        knowledge_base_id: str,
        payload: KnowledgeBaseUpdate,
        owner_id: str | None = None,
    ) -> KnowledgeBase:
        knowledge_base = self.get_knowledge_base(knowledge_base_id, owner_id)
        try:
            updated = self.repository.update(
                knowledge_base,
                name=payload.name,
                description=payload.description,
                update_name="name" in payload.model_fields_set,
                update_description="description" in payload.model_fields_set,
                web_access_policy=payload.web_access_policy,
                update_web_access_policy=(
                    "web_access_policy" in payload.model_fields_set
                ),
            )
            self.db.commit()
            return updated
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictException("同名知识库已存在") from exc
        except Exception:
            self.db.rollback()
            raise

    def get_knowledge_base(
        self, knowledge_base_id: str, owner_id: str | None = None
    ) -> KnowledgeBase:
        """Return one knowledge base or a safe 404 error."""
        knowledge_base = self.repository.get_by_id(knowledge_base_id, owner_id)
        if knowledge_base is None:
            self.db.rollback()
            raise ResourceNotFoundException("知识库不存在")
        return knowledge_base

    def delete_knowledge_base(
        self, knowledge_base_id: str, owner_id: str | None = None
    ) -> KnowledgeBase:
        """Delete an empty knowledge base and reject dependent records."""
        lock = (
            self.runtime.admin_operation("delete_knowledge_base")
            if self.runtime is not None
            else nullcontext()
        )
        vector_lock = (
            self.runtime.vector_write_lock
            if self.runtime is not None
            else nullcontext()
        )
        with lock, vector_lock:
            knowledge_base = self.repository.get_by_id(
                knowledge_base_id, owner_id
            )
            if knowledge_base is None:
                self.db.rollback()
                raise ResourceNotFoundException("知识库不存在")
            if knowledge_base.rebuild_status is RebuildStatus.BUILDING:
                raise ConflictException("知识库正在重建，不能删除")
            if self.files.has_processing(knowledge_base_id):
                raise ConflictException("知识库存在 PROCESSING 文件，不能删除")
            if self.repository.has_dependencies(knowledge_base_id):
                self.db.rollback()
                raise ConflictException("知识库包含文件或会话，不能删除")
            if self.jobs.has_nonterminal(
                resource_type="KNOWLEDGE_BASE",
                resource_id=knowledge_base_id,
            ):
                raise ConflictException("知识库仍被非终态 Job 引用")
            for collection_name in (
                knowledge_base.active_collection_name,
                knowledge_base.previous_collection_name,
                knowledge_base.building_collection_name,
                knowledge_base.cleanup_collection_name,
            ):
                if (
                    collection_name
                    and self.jobs.collection_is_pinned(collection_name)
                ):
                    raise ConflictException(
                        "知识库 Collection 正被评估 Job pin，不能删除"
                    )

            snapshots: list[CollectionSnapshot] = []
            if self.runtime is not None:
                names = [
                    name
                    for name in dict.fromkeys(
                        (
                            knowledge_base.active_collection_name,
                            knowledge_base.previous_collection_name,
                            knowledge_base.building_collection_name,
                            knowledge_base.cleanup_collection_name,
                        )
                    )
                    if name
                ]
                referenced_names = [
                    name
                    for name in (
                        knowledge_base.active_collection_name,
                        knowledge_base.previous_collection_name,
                        knowledge_base.building_collection_name,
                        knowledge_base.cleanup_collection_name,
                    )
                    if name
                ]
                if len(referenced_names) != len(set(referenced_names)):
                    raise ConflictException("知识库 Collection 指针存在重复引用")
                role_by_name: dict[str, tuple[str | None, str]] = {}
                for name, config_hash, role in (
                    (
                        knowledge_base.active_collection_name,
                        knowledge_base.active_embedding_config_hash,
                        "active",
                    ),
                    (
                        knowledge_base.previous_collection_name,
                        knowledge_base.previous_embedding_config_hash,
                        "previous",
                    ),
                    (
                        knowledge_base.building_collection_name,
                        knowledge_base.building_embedding_config_hash,
                        "building",
                    ),
                    (knowledge_base.cleanup_collection_name, None, "cleanup"),
                ):
                    if name:
                        role_by_name[name] = (config_hash, role)
                for name in names:
                    config_hash, role = role_by_name[name]
                    self.runtime.vector_store.get_collection(
                        name,
                        knowledge_base_id=knowledge_base.id,
                        expected_config_hash=config_hash,
                        role=role,
                        for_write=False,
                    )
                    snapshot = self.runtime.vector_store.snapshot_collection(name)
                    if (
                        str(snapshot.metadata.get("knowledge_base_id"))
                        != knowledge_base.id
                    ):
                        raise ConflictException("Collection 知识库归属不一致")
                    snapshots.append(snapshot)
                deleted: list[CollectionSnapshot] = []
                try:
                    for snapshot in snapshots:
                        self.runtime.vector_store.delete_collection(snapshot.name)
                        deleted.append(snapshot)
                except Exception:
                    for snapshot in deleted:
                        try:
                            self.runtime.vector_store.restore_collection(snapshot)
                        except Exception:
                            logger.critical(
                                "知识库 Collection 删除补偿失败（kb_id=%s, collection=%s）",
                                knowledge_base.id,
                                snapshot.name,
                                exc_info=True,
                            )
                    raise

            try:
                # Keep the proven-empty relationship available to the response
                # mapper after commit detaches the deleted instance.
                list(knowledge_base.files)
                self.repository.delete(knowledge_base)
                self.db.commit()
                return knowledge_base
            except Exception:
                self.db.rollback()
                if self.runtime is not None:
                    for snapshot in snapshots:
                        self.runtime.vector_store.restore_collection(snapshot)
                raise

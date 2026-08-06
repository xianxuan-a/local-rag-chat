"""Knowledge-base retrieval over the database-selected active Collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import time
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    ConflictException,
    ResourceNotFoundException,
    ValidationException,
    VectorStoreException,
)
from app.core.logger import get_logger
from app.core.observability import RETRIEVAL_DURATION
from app.models import FileRecord
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.schemas.chat import SourceReference
from app.services.runtime_coordinator import RuntimeCoordinator
from app.utils.text_utils import clean_text, truncate_text


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """Internal retrieval result with full content and public preview data."""

    content: str
    file_id: UUID
    file_name: str
    chunk_id: str
    content_preview: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: Literal["knowledge_base", "web"] = "knowledge_base"
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    published_at: datetime | None = None
    accessed_at: datetime | None = None

    def to_source_reference(self, citation_number: int = 1) -> SourceReference:
        return SourceReference(
            citation_number=citation_number,
            source_type=self.source_type,
            reference=(
                f"[K{citation_number}]"
                if self.source_type == "knowledge_base"
                else f"[W{citation_number}]"
            ),
            title=self.title or self.file_name,
            file_id=self.file_id,
            file_name=self.file_name,
            chunk_id=self.chunk_id,
            url=self.url,
            domain=self.domain,
            published_at=self.published_at,
            accessed_at=self.accessed_at,
            content_preview=self.content_preview,
            score=self.score,
            metadata=self.metadata,
        )


class RetrievalService:
    """Validate, search, filter, deduplicate, and map source references."""

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

    def retrieve(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[SourceReference]:
        """Return the existing public, preview-only source representation."""

        chunks = self.retrieve_chunks(
            knowledge_base_id,
            query,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        return [
            chunk.to_source_reference(index)
            for index, chunk in enumerate(chunks, start=1)
        ]

    def retrieve_chunks(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
        *,
        explicit_collection_name: str | None = None,
        explicit_config_hash: str | None = None,
        require_active_index: bool = False,
        apply_default_threshold: bool = True,
    ) -> list[RetrievedChunk]:
        """Return validated retrieval results with full stored chunk content."""

        normalized_query = clean_text(query)
        if not normalized_query:
            return []
        resolved_top_k = self.settings.RETRIEVAL_TOP_K if top_k is None else top_k
        if (
            isinstance(resolved_top_k, bool)
            or not isinstance(resolved_top_k, int)
            or not 1 <= resolved_top_k <= 100
        ):
            raise ValidationException("top_k 必须是 1 到 100 之间的整数")
        resolved_threshold = (
            self.settings.RETRIEVAL_SCORE_THRESHOLD
            if score_threshold is None and apply_default_threshold
            else score_threshold
        )
        if resolved_threshold is not None and (
            isinstance(resolved_threshold, bool)
            or not isinstance(resolved_threshold, (int, float))
            or not -1.0 <= float(resolved_threshold) <= 1.0
        ):
            raise ValidationException("score_threshold 必须位于 -1 到 1")

        knowledge_base = self.knowledge_bases.get_by_id(knowledge_base_id)
        if knowledge_base is None:
            raise ResourceNotFoundException("知识库不存在")
        collection_name = (
            explicit_collection_name
            if explicit_collection_name is not None
            else knowledge_base.active_collection_name
        )
        config_hash = (
            explicit_config_hash
            if explicit_collection_name is not None
            else knowledge_base.active_embedding_config_hash
        )
        if not collection_name:
            if require_active_index:
                raise ConflictException("知识库没有可检索的活动索引")
            return []
        if not config_hash:
            raise VectorStoreException("活动 Collection 缺少配置哈希")
        if explicit_collection_name is None and collection_name in {
            knowledge_base.previous_collection_name,
            knowledge_base.building_collection_name,
            knowledge_base.cleanup_collection_name,
        }:
            raise VectorStoreException("活动 Collection 与其他数据库指针冲突")

        collection = self.runtime.vector_store.get_collection(
            collection_name,
            knowledge_base_id=knowledge_base.id,
            expected_config_hash=config_hash,
            role="active" if explicit_collection_name is None else None,
            for_write=False,
        )
        if collection.count() == 0:
            has_active = self.db.scalar(
                select(
                    exists().where(
                        FileRecord.knowledge_base_id == knowledge_base.id,
                        FileRecord.has_active_vectors.is_(True),
                    )
                )
            )
            if has_active:
                logger.critical(
                    "活动 Collection 为空但数据库声明存在有效向量（kb_id=%s, collection=%s）",
                    knowledge_base.id,
                    collection_name,
                )
                raise VectorStoreException(
                    "活动 Collection 与文件索引状态不一致，需要整库重建"
                )
            if require_active_index:
                raise ConflictException("知识库的活动索引为空")
            return []

        retrieval_started = time.perf_counter()
        try:
            raw_results = self.runtime.vector_store.similarity_search(
                normalized_query,
                top_k=resolved_top_k,
                score_threshold=(
                    float(resolved_threshold)
                    if resolved_threshold is not None
                    else None
                ),
                collection_name=collection_name,
                knowledge_base_id=knowledge_base.id,
                config_hash=config_hash,
            )
        finally:
            RETRIEVAL_DURATION.observe(
                max(0.0, time.perf_counter() - retrieval_started)
            )
        raw_results.sort(key=lambda item: (-item.score, item.vector_id))

        deduplicated: dict[tuple[str, str], RetrievedChunk] = {}
        for result in raw_results:
            metadata = result.document.metadata
            content = result.document.page_content
            if not isinstance(content, str):
                raise VectorStoreException("检索结果缺少完整分块正文")
            if (
                str(metadata.get("knowledge_base_id")) != knowledge_base.id
                or metadata.get("embedding_config_hash") != config_hash
                or not content.strip()
            ):
                logger.warning(
                    "跳过归属或配置异常的检索结果（kb_id=%s, vector_id=%s）",
                    knowledge_base.id,
                    result.vector_id,
                )
                continue
            raw_file_id = metadata.get("file_id")
            try:
                parsed_file_id = UUID(str(raw_file_id))
            except (TypeError, ValueError):
                logger.warning(
                    "跳过 file_id 无效的检索结果（kb_id=%s, vector_id=%s）",
                    knowledge_base.id,
                    result.vector_id,
                )
                continue
            chunk_id = metadata.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                content_hash = sha256(
                    clean_text(content).encode("utf-8")
                ).hexdigest()
                chunk_id = f"legacy_{content_hash}"
                logger.warning(
                    "检索结果缺少 chunk_id，使用正文哈希兜底（kb_id=%s, vector_id=%s）",
                    knowledge_base.id,
                    result.vector_id,
                )
            file_name = metadata.get("file_name")
            if not isinstance(file_name, str) or not file_name.strip():
                file_name = "unknown"
            key = (str(parsed_file_id), chunk_id)
            if key in deduplicated:
                continue
            deduplicated[key] = RetrievedChunk(
                content=content,
                file_id=parsed_file_id,
                file_name=file_name,
                chunk_id=chunk_id[:100],
                content_preview=truncate_text(
                    content,
                    1000,
                ),
                score=result.score,
                metadata=self._public_metadata(metadata),
            )
            if len(deduplicated) >= resolved_top_k:
                break
        return list(deduplicated.values())

    @staticmethod
    def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "file_type",
            "source",
            "source_index",
            "encoding",
            "record_index",
            "row",
            "page",
            "total_pages",
            "chunk_index",
        }
        return {
            key: value
            for key, value in metadata.items()
            if key in allowed
            and (
                value is None
                or isinstance(value, (str, int, float, bool))
            )
        }

    def retrieve_chunks_from_collection(
        self,
        *,
        knowledge_base_id: str,
        collection_name: str,
        embedding_config_hash: str,
        query: str,
        top_k: int,
        score_threshold: float | None,
    ) -> list[RetrievedChunk]:
        """Internal evaluation path pinned to an immutable collection identity."""

        return self.retrieve_chunks(
            knowledge_base_id,
            query,
            top_k=top_k,
            score_threshold=score_threshold,
            explicit_collection_name=collection_name,
            explicit_config_hash=embedding_config_hash,
        )

"""Persistent Chroma operations using only application-precomputed vectors."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import threading
from typing import Any, Literal
from uuid import uuid4

import chromadb
from chromadb.errors import NotFoundError
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.config import Settings
from app.core.exceptions import (
    ModelServiceException,
    ValidationException,
    VectorStoreException,
)
from app.core.logger import get_logger
from app.core.observability import EMBEDDING_ERRORS
from app.services.embedding_service import (
    DashScopeEmbeddingAdapter,
    EmbeddingConfig,
)


logger = get_logger(__name__)
Lifecycle = Literal["BUILDING", "ACTIVE", "RETIRED", "FAILED"]
CollectionRole = Literal["active", "previous", "building", "cleanup"]


@dataclass(slots=True)
class VectorSnapshot:
    """Complete restorable rows from one Collection."""

    ids: list[str]
    documents: list[str]
    metadatas: list[dict[str, Any]]
    embeddings: list[list[float]]

    @classmethod
    def empty(cls) -> "VectorSnapshot":
        return cls(ids=[], documents=[], metadatas=[], embeddings=[])


@dataclass(slots=True)
class CollectionSnapshot:
    name: str
    metadata: dict[str, Any]
    configuration: dict[str, Any]
    vectors: VectorSnapshot


@dataclass(slots=True)
class VectorWriteReceipt:
    collection_name: str
    knowledge_base_id: str
    file_id: str
    new_ids: list[str]
    previous: VectorSnapshot


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    vector_id: str
    document: Document
    distance: float
    score: float


class VectorStoreService:
    """Own Chroma persistence, collection contracts, and vector compensation."""

    def __init__(
        self,
        settings: Settings,
        *,
        write_lock: threading.RLock | None = None,
        embedding_factory: Callable[[EmbeddingConfig], Embeddings] | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._write_lock = write_lock or threading.RLock()
        self._client = client
        self._client_lock = threading.Lock()
        self._embedding_factory = embedding_factory or self._create_embeddings
        self._embedding_cache: dict[str, Embeddings] = {}
        self._embedding_lock = threading.Lock()

    @property
    def current_config(self) -> EmbeddingConfig:
        config = EmbeddingConfig.from_settings(self.settings)
        config.validate_supported()
        return config

    @property
    def current_config_hash(self) -> str:
        return self.current_config.config_hash

    @property
    def client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    Path(self.settings.CHROMA_DIR).mkdir(parents=True, exist_ok=True)
                    self._client = chromadb.PersistentClient(
                        path=str(Path(self.settings.CHROMA_DIR).resolve())
                    )
        return self._client

    def _create_embeddings(self, config: EmbeddingConfig) -> Embeddings:
        return DashScopeEmbeddingAdapter(self.settings, config)

    def get_embeddings(self, config: EmbeddingConfig) -> Embeddings:
        config.validate_supported()
        cache_key = self._runtime_embedding_key(config)
        cached = self._embedding_cache.get(cache_key)
        if cached is not None:
            return cached
        with self._embedding_lock:
            cached = self._embedding_cache.get(cache_key)
            if cached is None:
                try:
                    cached = self._embedding_factory(config)
                except (ValidationException, ModelServiceException):
                    raise
                except Exception as exc:
                    raise ModelServiceException(
                        "Embedding 适配器初始化失败"
                    ) from exc
                self._embedding_cache[cache_key] = cached
            return cached

    def _runtime_embedding_key(self, config: EmbeddingConfig) -> str:
        secret = self.settings.DASHSCOPE_API_KEY.get_secret_value()
        secret_fingerprint = sha256(secret.encode("utf-8")).hexdigest()
        payload = json.dumps(
            {
                "config_hash": config.config_hash,
                "base_url": self.settings.DASHSCOPE_BASE_URL,
                "timeout": self.settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS,
                "retries": self.settings.EMBEDDING_MAX_RETRIES,
                "key_fingerprint": secret_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_collection_name(
        knowledge_base_id: str,
        config_hash: str,
        generation: str | None = None,
    ) -> tuple[str, str]:
        generation_value = (generation or uuid4().hex).replace("-", "")[:12]
        kb_hash = sha256(str(knowledge_base_id).encode("utf-8")).hexdigest()[:16]
        return (
            f"kb_{kb_hash}_{config_hash[:16]}_{generation_value}",
            generation_value,
        )

    def create_collection(
        self,
        *,
        name: str,
        knowledge_base_id: str,
        config: EmbeddingConfig,
        generation: str,
        lifecycle_status: Lifecycle = "BUILDING",
    ) -> Any:
        metadata = self.build_collection_metadata(
            knowledge_base_id=knowledge_base_id,
            config=config,
            generation=generation,
            lifecycle_status=lifecycle_status,
        )
        with self._write_lock:
            try:
                collection = self.client.create_collection(
                    name=name,
                    configuration={"hnsw": {"space": "cosine"}},
                    metadata=metadata,
                    embedding_function=None,
                )
            except Exception as exc:
                raise VectorStoreException("创建 Chroma Collection 失败") from exc
        self.validate_collection(
            collection,
            knowledge_base_id=knowledge_base_id,
            expected_config_hash=config.config_hash,
        )
        return collection

    @staticmethod
    def build_collection_metadata(
        *,
        knowledge_base_id: str,
        config: EmbeddingConfig,
        generation: str,
        lifecycle_status: Lifecycle,
    ) -> dict[str, str | int]:
        return {
            "knowledge_base_id": str(knowledge_base_id),
            "embedding_provider": config.provider,
            "embedding_model": config.model,
            "embedding_dimension": config.dimension,
            "embedding_normalization": config.normalization,
            "distance_metric": config.distance_metric,
            "embedding_protocol_version": config.protocol_version,
            "embedding_config_hash": config.config_hash,
            "generation": generation,
            "lifecycle_status": lifecycle_status,
        }

    def collection_exists(self, name: str) -> bool:
        try:
            self.client.get_collection(name=name, embedding_function=None)
        except NotFoundError:
            return False
        except Exception as exc:
            raise VectorStoreException("读取 Chroma Collection 失败") from exc
        return True

    def list_collections(self) -> list[Any]:
        """Return Chroma collection handles without installing embedding functions."""

        try:
            listed = self.client.list_collections()
            collections: list[Any] = []
            for item in listed:
                if isinstance(item, str):
                    collections.append(
                        self.client.get_collection(
                            name=item,
                            embedding_function=None,
                        )
                    )
                else:
                    collections.append(item)
            return collections
        except Exception as exc:
            raise VectorStoreException("列出 Chroma Collection 失败") from exc

    def get_collection(
        self,
        name: str,
        *,
        knowledge_base_id: str | None = None,
        expected_config_hash: str | None = None,
        role: CollectionRole | None = None,
        for_write: bool = False,
    ) -> Any:
        try:
            collection = self.client.get_collection(
                name=name,
                embedding_function=None,
            )
        except NotFoundError as exc:
            raise VectorStoreException("活动 Collection 不存在") from exc
        except Exception as exc:
            raise VectorStoreException("读取 Chroma Collection 失败") from exc
        self.validate_collection(
            collection,
            knowledge_base_id=knowledge_base_id,
            expected_config_hash=expected_config_hash,
        )
        if role is not None:
            self.validate_lifecycle(collection, role=role, for_write=for_write)
        return collection

    def validate_collection(
        self,
        collection: Any,
        *,
        knowledge_base_id: str | None = None,
        expected_config_hash: str | None = None,
    ) -> None:
        metadata = collection.metadata
        configuration = collection.configuration
        if not isinstance(metadata, dict):
            raise VectorStoreException("Collection metadata 缺失")
        required = {
            "knowledge_base_id",
            "embedding_provider",
            "embedding_model",
            "embedding_dimension",
            "embedding_normalization",
            "distance_metric",
            "embedding_protocol_version",
            "embedding_config_hash",
            "generation",
            "lifecycle_status",
        }
        if required - set(metadata):
            raise VectorStoreException("Collection metadata 不完整")
        if knowledge_base_id is not None and str(
            metadata["knowledge_base_id"]
        ) != str(knowledge_base_id):
            raise VectorStoreException("Collection 知识库归属不一致")
        if (
            expected_config_hash is not None
            and metadata["embedding_config_hash"] != expected_config_hash
        ):
            raise VectorStoreException("Collection Embedding 配置哈希不一致")
        config = EmbeddingConfig.from_metadata(metadata)
        if config.config_hash != metadata["embedding_config_hash"]:
            raise VectorStoreException("Collection Embedding metadata 自相矛盾")
        if not isinstance(configuration, dict):
            raise VectorStoreException("Collection configuration 缺失")
        hnsw = configuration.get("hnsw")
        if not isinstance(hnsw, dict) or hnsw.get("space") != "cosine":
            raise VectorStoreException("Collection 真实 HNSW 空间不是 cosine")
        if configuration.get("embedding_function") is not None:
            raise VectorStoreException("Collection 禁止配置内部 EmbeddingFunction")

    @staticmethod
    def validate_lifecycle(
        collection: Any,
        *,
        role: CollectionRole,
        for_write: bool,
    ) -> None:
        status = collection.metadata.get("lifecycle_status")
        if role == "active":
            if status == "ACTIVE":
                return
            if status == "RETIRED" and not for_write:
                logger.error(
                    "活动 Collection lifecycle 漂移为 RETIRED（collection=%s）",
                    collection.name,
                )
                return
            raise VectorStoreException("活动 Collection lifecycle 冲突")
        if role == "previous":
            if status in {"RETIRED", "ACTIVE"}:
                if status == "ACTIVE":
                    logger.error(
                        "Previous Collection lifecycle 漂移为 ACTIVE（collection=%s）",
                        collection.name,
                    )
                return
            raise VectorStoreException("Previous Collection lifecycle 冲突")
        if role == "building" and status in {"BUILDING", "FAILED"}:
            if for_write and status != "BUILDING":
                raise VectorStoreException("FAILED 候选 Collection 禁止写入")
            return
        if role == "cleanup" and status in {"RETIRED", "FAILED"}:
            return
        raise VectorStoreException("Collection lifecycle 与数据库指针冲突")

    def set_lifecycle(self, name: str, lifecycle_status: Lifecycle) -> None:
        with self._write_lock:
            collection = self.get_collection(name)
            metadata = dict(collection.metadata)
            metadata["lifecycle_status"] = lifecycle_status
            try:
                collection.modify(metadata=metadata)
            except Exception as exc:
                raise VectorStoreException("更新 Collection lifecycle 失败") from exc

    def embed_documents(
        self,
        documents: Sequence[Document],
        config: EmbeddingConfig,
    ) -> list[list[float]]:
        if not documents:
            raise ValidationException("待向量化文档不能为空")
        texts = [document.page_content for document in documents]
        try:
            vectors = self.get_embeddings(config).embed_documents(texts)
            return self._normalize_vectors(
                vectors, len(texts), config.dimension
            )
        except Exception:
            EMBEDDING_ERRORS.inc()
            raise

    def embed_query(self, query: str, config: EmbeddingConfig) -> list[float]:
        try:
            vector = self.get_embeddings(config).embed_query(query)
            return self._normalize_vectors([vector], 1, config.dimension)[0]
        except Exception:
            EMBEDDING_ERRORS.inc()
            raise

    @staticmethod
    def _normalize_vectors(
        vectors: Any,
        expected_count: int,
        dimension: int,
    ) -> list[list[float]]:
        if not isinstance(vectors, list) or len(vectors) != expected_count:
            raise ModelServiceException("Embedding 返回向量数量不匹配")
        normalized: list[list[float]] = []
        for vector in vectors:
            if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
                raise ModelServiceException("Embedding 返回向量维度不匹配")
            values: list[float] = []
            for item in vector:
                if isinstance(item, bool):
                    raise ModelServiceException("Embedding 向量包含非法数值")
                try:
                    value = float(item)
                except (TypeError, ValueError) as exc:
                    raise ModelServiceException("Embedding 向量包含非法数值") from exc
                if not math.isfinite(value):
                    raise ModelServiceException("Embedding 向量包含非有限值")
                values.append(value)
            norm = math.sqrt(sum(value * value for value in values))
            if norm == 0:
                raise ModelServiceException("Embedding 返回零向量")
            normalized.append([value / norm for value in values])
        return normalized

    @staticmethod
    def vector_id(
        knowledge_base_id: str,
        file_id: str,
        chunk_id: str,
    ) -> str:
        payload = json.dumps(
            {
                "knowledge_base_id": str(knowledge_base_id),
                "file_id": str(file_id),
                "chunk_id": str(chunk_id),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def prepare_documents(
        self,
        documents: Sequence[Document],
        *,
        knowledge_base_id: str,
        file_id: str,
        config: EmbeddingConfig,
        recovery_metadata: dict[str, str | int] | None = None,
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        ids: list[str] = []
        contents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        for document in documents:
            if not isinstance(document, Document) or not document.page_content.strip():
                raise ValidationException("向量文档正文不能为空")
            metadata = self._sanitize_metadata(document.metadata)
            if str(metadata.get("file_id")) != str(file_id):
                raise ValidationException("文档 file_id 不一致")
            if str(metadata.get("knowledge_base_id")) != str(knowledge_base_id):
                raise ValidationException("文档 knowledge_base_id 不一致")
            chunk_id = metadata.get("chunk_id")
            file_name = metadata.get("file_name")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValidationException("文档缺少 chunk_id")
            if not isinstance(file_name, str) or not file_name:
                raise ValidationException("文档缺少 file_name")
            if chunk_id in seen_chunk_ids:
                raise ValidationException("文档包含重复 chunk_id")
            seen_chunk_ids.add(chunk_id)
            metadata["embedding_config_hash"] = config.config_hash
            metadata["embedding_protocol_version"] = config.protocol_version
            if recovery_metadata:
                metadata.update(self._sanitize_metadata(recovery_metadata))
            ids.append(self.vector_id(knowledge_base_id, file_id, chunk_id))
            contents.append(document.page_content)
            metadatas.append(metadata)
        if not ids:
            raise ValidationException("待写入分块不能为空")
        return ids, contents, metadatas

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str) or not key:
                raise ValidationException("Chroma metadata 键必须是非空字符串")
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValidationException("Chroma metadata 包含非有限数值")
                sanitized[key] = value
                continue
            raise ValidationException(f"Chroma metadata 字段不可序列化：{key}")
        return sanitized

    def snapshot_file(
        self,
        collection_name: str,
        *,
        knowledge_base_id: str,
        file_id: str,
        expected_config_hash: str | None = None,
    ) -> VectorSnapshot:
        collection = self.get_collection(
            collection_name,
            knowledge_base_id=knowledge_base_id,
            expected_config_hash=expected_config_hash,
        )
        try:
            result = collection.get(
                where={"file_id": str(file_id)},
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception as exc:
            raise VectorStoreException("读取文件向量快照失败") from exc
        return self._snapshot_from_result(result)

    @staticmethod
    def _snapshot_from_result(result: dict[str, Any]) -> VectorSnapshot:
        ids = list(result.get("ids") or [])
        if not ids:
            return VectorSnapshot.empty()
        documents = list(result.get("documents") or [])
        metadatas = [dict(item) for item in (result.get("metadatas") or [])]
        raw_embeddings = result.get("embeddings")
        embeddings = (
            raw_embeddings.tolist()
            if hasattr(raw_embeddings, "tolist")
            else list(raw_embeddings or [])
        )
        if not (
            len(ids)
            == len(documents)
            == len(metadatas)
            == len(embeddings)
        ):
            raise VectorStoreException("Chroma 快照字段数量不一致")
        return VectorSnapshot(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=[[float(value) for value in row] for row in embeddings],
        )

    def restore_snapshot(self, collection_name: str, snapshot: VectorSnapshot) -> None:
        if not snapshot.ids:
            return
        with self._write_lock:
            collection = self.get_collection(collection_name)
            try:
                self._upsert_precomputed(
                    collection,
                    ids=snapshot.ids,
                    documents=snapshot.documents,
                    metadatas=snapshot.metadatas,
                    embeddings=snapshot.embeddings,
                )
            except Exception as exc:
                raise VectorStoreException("恢复 Chroma 向量快照失败") from exc

    @staticmethod
    def _validate_write_payload(
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        count = len(ids)
        if count == 0 or not (
            count == len(documents) == len(metadatas) == len(embeddings)
        ):
            raise ValidationException("Chroma 写入字段数量不一致或为空")
        if len(set(ids)) != count:
            raise ValidationException("Chroma 写入包含重复 ID")
        if any(not document for document in documents):
            raise ValidationException("Chroma 写入正文不能为空")
        if any(not embedding for embedding in embeddings):
            raise ValidationException("Chroma 写入 embeddings 不能为空")

    @classmethod
    def _upsert_precomputed(
        cls,
        collection: Any,
        *,
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Single audited path for Chroma writes with application vectors."""

        cls._validate_write_payload(ids, documents, metadatas, embeddings)
        collection.upsert(
            ids=list(ids),
            documents=list(documents),
            metadatas=list(metadatas),
            embeddings=[list(vector) for vector in embeddings],
        )

    def replace_file_documents(
        self,
        *,
        collection_name: str,
        knowledge_base_id: str,
        file_id: str,
        documents: Sequence[Document],
        embeddings: Sequence[Sequence[float]],
        config: EmbeddingConfig,
        role: Literal["active", "building"],
        processing_job_id: str | None = None,
        vector_run_id: str | None = None,
        expected_chunk_count: int | None = None,
    ) -> VectorWriteReceipt:
        recovery_metadata: dict[str, str | int] = {
            "target_collection": collection_name,
        }
        if processing_job_id is not None:
            recovery_metadata["processing_job_id"] = processing_job_id
        if vector_run_id is not None:
            recovery_metadata["vector_run_id"] = vector_run_id
        if expected_chunk_count is not None:
            recovery_metadata["expected_chunk_count"] = expected_chunk_count
        ids, contents, metadatas = self.prepare_documents(
            documents,
            knowledge_base_id=knowledge_base_id,
            file_id=file_id,
            config=config,
            recovery_metadata=recovery_metadata,
        )
        normalized = self._normalize_vectors(
            [list(vector) for vector in embeddings],
            len(ids),
            config.dimension,
        )
        self._validate_write_payload(ids, contents, metadatas, normalized)

        with self._write_lock:
            collection = self.get_collection(
                collection_name,
                knowledge_base_id=knowledge_base_id,
                expected_config_hash=config.config_hash,
                role=role,
                for_write=True,
            )
            previous = self.snapshot_file(
                collection_name,
                knowledge_base_id=knowledge_base_id,
                file_id=file_id,
                expected_config_hash=config.config_hash,
            )
            try:
                self._upsert_precomputed(
                    collection,
                    ids=ids,
                    documents=contents,
                    metadatas=metadatas,
                    embeddings=normalized,
                )
                self._verify_file_rows(
                    collection,
                    file_id=file_id,
                    expected_ids=set(ids),
                    expected_documents=dict(zip(ids, contents, strict=True)),
                    expected_metadatas=dict(zip(ids, metadatas, strict=True)),
                    allow_extra=True,
                )
                stale_ids = sorted(set(previous.ids) - set(ids))
                if stale_ids:
                    collection.delete(ids=stale_ids)
                self._verify_file_rows(
                    collection,
                    file_id=file_id,
                    expected_ids=set(ids),
                    expected_documents=dict(zip(ids, contents, strict=True)),
                    expected_metadatas=dict(zip(ids, metadatas, strict=True)),
                )
            except Exception as exc:
                try:
                    collection.delete(ids=ids)
                    self.restore_snapshot(collection_name, previous)
                except Exception as compensation_exc:
                    logger.critical(
                        "文件向量写入补偿失败（kb_id=%s, file_id=%s, collection=%s）",
                        knowledge_base_id,
                        file_id,
                        collection_name,
                        exc_info=True,
                    )
                    raise VectorStoreException(
                        "索引补偿失败，需要执行知识库重建修复"
                    ) from compensation_exc
                if isinstance(exc, (ValidationException, VectorStoreException)):
                    raise
                raise VectorStoreException("写入文件向量失败") from exc
        return VectorWriteReceipt(
            collection_name=collection_name,
            knowledge_base_id=str(knowledge_base_id),
            file_id=str(file_id),
            new_ids=ids,
            previous=previous,
        )

    @staticmethod
    def _verify_file_rows(
        collection: Any,
        *,
        file_id: str,
        expected_ids: set[str],
        expected_documents: dict[str, str],
        expected_metadatas: dict[str, dict[str, Any]],
        allow_extra: bool = False,
    ) -> None:
        result = collection.get(
            where={"file_id": str(file_id)},
            include=["documents", "metadatas"],
        )
        actual_ids = list(result.get("ids") or [])
        actual_set = set(actual_ids)
        ids_match = (
            expected_ids.issubset(actual_set)
            if allow_extra
            else actual_set == expected_ids and len(actual_ids) == len(expected_ids)
        )
        if not ids_match:
            raise VectorStoreException("文件向量 ID 完整性校验失败")
        documents = list(result.get("documents") or [])
        metadatas = list(result.get("metadatas") or [])
        for vector_id, document, metadata in zip(
            actual_ids, documents, metadatas, strict=True
        ):
            if vector_id not in expected_ids:
                continue
            if document != expected_documents[vector_id]:
                raise VectorStoreException("文件向量正文校验失败")
            expected = expected_metadatas[vector_id]
            for key in (
                "file_id",
                "knowledge_base_id",
                "chunk_id",
                "file_name",
                "embedding_config_hash",
                "embedding_protocol_version",
            ):
                if metadata.get(key) != expected.get(key):
                    raise VectorStoreException("文件向量 metadata 校验失败")

    def rollback_write(self, receipt: VectorWriteReceipt) -> None:
        with self._write_lock:
            collection = self.get_collection(receipt.collection_name)
            try:
                if receipt.new_ids:
                    collection.delete(ids=receipt.new_ids)
                self.restore_snapshot(receipt.collection_name, receipt.previous)
            except Exception as exc:
                raise VectorStoreException(
                    "索引补偿失败，需要执行知识库重建修复"
                ) from exc

    def delete_ids(self, collection_name: str, ids: Sequence[str]) -> None:
        if not ids:
            return
        with self._write_lock:
            collection = self.get_collection(collection_name)
            try:
                collection.delete(ids=list(ids))
            except Exception as exc:
                raise VectorStoreException("按 ID 删除向量失败") from exc

    def delete_by_file_id(
        self,
        file_id: str,
        *,
        knowledge_base_id: str,
        collection_names: Sequence[str],
    ) -> dict[str, VectorSnapshot]:
        snapshots: dict[str, VectorSnapshot] = {}
        with self._write_lock:
            for name in dict.fromkeys(collection_names):
                snapshot = self.snapshot_file(
                    name,
                    knowledge_base_id=knowledge_base_id,
                    file_id=file_id,
                )
                snapshots[name] = snapshot
                if snapshot.ids:
                    try:
                        self.get_collection(name).delete(ids=snapshot.ids)
                    except Exception as exc:
                        self.restore_file_snapshots(snapshots)
                        raise VectorStoreException("删除文件向量失败") from exc
        return snapshots

    def restore_file_snapshots(
        self, snapshots: dict[str, VectorSnapshot]
    ) -> None:
        with self._write_lock:
            for name, snapshot in snapshots.items():
                self.restore_snapshot(name, snapshot)

    def similarity_search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float | None = None,
        *,
        collection_name: str,
        knowledge_base_id: str,
        config_hash: str,
    ) -> list[VectorSearchResult]:
        collection = self.get_collection(
            collection_name,
            knowledge_base_id=knowledge_base_id,
            expected_config_hash=config_hash,
            role="active",
            for_write=False,
        )
        count = collection.count()
        if count == 0:
            return []
        config = EmbeddingConfig.from_metadata(collection.metadata)
        query_vector = self.embed_query(query, config)
        candidate_count = min(top_k * 4, count)
        try:
            result = collection.query(
                query_embeddings=[query_vector],
                n_results=candidate_count,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise VectorStoreException("Chroma 相似度查询失败") from exc
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        output: list[VectorSearchResult] = []
        for vector_id, content, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            raw_score = 1.0 - float(distance)
            if 1.0 < raw_score <= 1.0 + 1e-6:
                raw_score = 1.0
            if -1.0 - 1e-6 <= raw_score < -1.0:
                raw_score = -1.0
            if not -1.0 <= raw_score <= 1.0:
                raise VectorStoreException("Chroma cosine distance 超出有效范围")
            if score_threshold is not None and raw_score < score_threshold:
                continue
            output.append(
                VectorSearchResult(
                    vector_id=vector_id,
                    document=Document(
                        page_content=content or "",
                        metadata=dict(metadata or {}),
                    ),
                    distance=float(distance),
                    score=raw_score,
                )
            )
        return output

    def snapshot_collection(
        self, name: str, *, batch_size: int = 500
    ) -> CollectionSnapshot:
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        collection = self.get_collection(name)
        vectors = VectorSnapshot.empty()
        try:
            expected_count = int(collection.count())
            for offset in range(0, expected_count, batch_size):
                batch = self._snapshot_from_result(
                    collection.get(
                        include=["documents", "metadatas", "embeddings"],
                        limit=batch_size,
                        offset=offset,
                    )
                )
                vectors.ids.extend(batch.ids)
                vectors.documents.extend(batch.documents)
                vectors.metadatas.extend(batch.metadatas)
                vectors.embeddings.extend(batch.embeddings)
        except Exception as exc:
            raise VectorStoreException("读取 Collection 快照失败") from exc
        if (
            len(vectors.ids) != expected_count
            or len(set(vectors.ids)) != len(vectors.ids)
        ):
            raise VectorStoreException("Collection 分批快照数量或 ID 唯一性校验失败")
        return CollectionSnapshot(
            name=name,
            metadata=dict(collection.metadata),
            configuration=dict(collection.configuration),
            vectors=vectors,
        )

    def delete_collection(self, name: str) -> None:
        with self._write_lock:
            try:
                self.client.delete_collection(name=name)
            except NotFoundError:
                return
            except Exception as exc:
                raise VectorStoreException("删除 Chroma Collection 失败") from exc

    def restore_collection(self, snapshot: CollectionSnapshot) -> None:
        config = EmbeddingConfig.from_metadata(snapshot.metadata)
        with self._write_lock:
            if self.collection_exists(snapshot.name):
                self.delete_collection(snapshot.name)
            collection = self.client.create_collection(
                name=snapshot.name,
                configuration=snapshot.configuration,
                metadata=snapshot.metadata,
                embedding_function=None,
            )
            if snapshot.vectors.ids:
                for offset in range(0, len(snapshot.vectors.ids), 500):
                    end = offset + 500
                    self._upsert_precomputed(
                        collection,
                        ids=snapshot.vectors.ids[offset:end],
                        documents=snapshot.vectors.documents[offset:end],
                        metadatas=snapshot.vectors.metadatas[offset:end],
                        embeddings=snapshot.vectors.embeddings[offset:end],
                    )
        self.validate_collection(
            collection,
            knowledge_base_id=str(snapshot.metadata["knowledge_base_id"]),
            expected_config_hash=config.config_hash,
        )

    def collection_file_counts(self, name: str) -> dict[str, int]:
        collection = self.get_collection(name)
        result = collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for metadata in result.get("metadatas") or []:
            file_id = metadata.get("file_id") if metadata else None
            if isinstance(file_id, str) and file_id:
                counts[file_id] = counts.get(file_id, 0) + 1
        return counts

    def validate_whole_collection(
        self,
        *,
        name: str,
        knowledge_base_id: str,
        config_hash: str,
        expected_file_ids: set[str],
        expected_counts: dict[str, int],
        role: CollectionRole = "building",
    ) -> None:
        collection = self.get_collection(
            name,
            knowledge_base_id=knowledge_base_id,
            expected_config_hash=config_hash,
            role=role,
            for_write=False,
        )
        result = collection.get(include=["metadatas", "embeddings", "documents"])
        snapshot = self._snapshot_from_result(result)
        counts: dict[str, int] = {}
        seen_chunks: set[tuple[str, str]] = set()
        for document, metadata, embedding in zip(
            snapshot.documents,
            snapshot.metadatas,
            snapshot.embeddings,
            strict=True,
        ):
            if not document:
                raise VectorStoreException("候选 Collection 包含空正文")
            if str(metadata.get("knowledge_base_id")) != str(knowledge_base_id):
                raise VectorStoreException("候选 Collection 包含其他知识库数据")
            if metadata.get("embedding_config_hash") != config_hash:
                raise VectorStoreException("候选 Collection 配置哈希不一致")
            file_id = metadata.get("file_id")
            chunk_id = metadata.get("chunk_id")
            if not isinstance(file_id, str) or not isinstance(chunk_id, str):
                raise VectorStoreException("候选 Collection 来源 metadata 缺失")
            identity = (file_id, chunk_id)
            if identity in seen_chunks:
                raise VectorStoreException("候选 Collection 包含重复分块")
            seen_chunks.add(identity)
            counts[file_id] = counts.get(file_id, 0) + 1
            if len(embedding) != int(collection.metadata["embedding_dimension"]):
                raise VectorStoreException("候选 Collection 向量维度不一致")
        if set(counts) != expected_file_ids or counts != expected_counts:
            raise VectorStoreException("候选 Collection 文件集合或数量不一致")

    def reset_collection(
        self,
        *,
        name: str,
        knowledge_base_id: str,
        config: EmbeddingConfig,
        generation: str,
    ) -> None:
        with self._write_lock:
            self.delete_collection(name)
            self.create_collection(
                name=name,
                knowledge_base_id=knowledge_base_id,
                config=config,
                generation=generation,
                lifecycle_status="BUILDING",
            )

    def add_documents(
        self,
        documents: Sequence[Document],
        ids: Sequence[str] | None = None,
        *,
        collection_name: str | None = None,
        embeddings: Sequence[Sequence[float]] | None = None,
    ) -> list[str]:
        """Compatibility entry that still requires an explicit target and vectors."""

        if collection_name is None or embeddings is None:
            raise ValidationException(
                "add_documents 必须显式提供 collection_name 和 embeddings"
            )
        if not documents:
            raise ValidationException("待写入文档不能为空")
        first = documents[0].metadata
        knowledge_base_id = str(first.get("knowledge_base_id") or "")
        file_id = str(first.get("file_id") or "")
        collection = self.get_collection(collection_name)
        config = EmbeddingConfig.from_metadata(collection.metadata)
        expected_ids, contents, metadatas = self.prepare_documents(
            documents,
            knowledge_base_id=knowledge_base_id,
            file_id=file_id,
            config=config,
        )
        if ids is not None and list(ids) != expected_ids:
            raise ValidationException("显式 IDs 与稳定向量 ID 不一致")
        normalized = self._normalize_vectors(
            [list(vector) for vector in embeddings],
            len(documents),
            config.dimension,
        )
        with self._write_lock:
            self._upsert_precomputed(
                collection,
                ids=expected_ids,
                documents=contents,
                metadatas=metadatas,
                embeddings=normalized,
            )
        return expected_ids

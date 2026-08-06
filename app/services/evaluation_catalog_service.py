"""Reusable evaluation datasets and immutable evaluation-run submission."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationException,
    ConflictException,
    ResourceNotFoundException,
)
from app.models import (
    EvaluationDataset,
    Job,
    JobStatus,
    JobType,
    KnowledgeBase,
    User,
    UserRole,
    new_uuid,
    utc_now,
)
from app.repositories.evaluation_dataset_repository import (
    EvaluationDatasetRepository,
)
from app.schemas.evaluation import EvaluationRunCreate
from app.services.evaluation_service import EvaluationDataset as ParsedDataset
from app.services.evaluation_service import parse_jsonl_dataset
from app.services.job_service import JobService
from app.services.runtime_coordinator import RuntimeCoordinator


class EvaluationCatalogService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        runtime: RuntimeCoordinator,
    ) -> None:
        self.db = db
        self.settings = settings
        self.runtime = runtime
        self.datasets = EvaluationDatasetRepository(db)

    def register_dataset(
        self,
        *,
        owner: User,
        name: str,
        description: str | None,
        original_filename: str,
        raw: bytes,
    ) -> EvaluationDataset:
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 100:
            raise ConflictException("数据集名称长度必须为 1 到 100 个字符")
        normalized_description = (description or "").strip() or None
        if normalized_description and len(normalized_description) > 1000:
            raise ConflictException("数据集说明不能超过 1000 个字符")
        parsed = parse_jsonl_dataset(raw)
        existing = self.datasets.get_by_owner_name(owner.id, normalized_name)
        if existing is not None:
            if existing.sha256 == parsed.sha256:
                return existing
            raise ConflictException("当前用户已存在同名评测数据集")

        storage_path = self._persist_dataset(parsed)
        dataset = EvaluationDataset(
            id=new_uuid(),
            owner_id=owner.id,
            name=normalized_name,
            description=normalized_description,
            original_filename=Path(original_filename or "dataset.jsonl").name[
                :255
            ],
            storage_path=str(storage_path),
            sha256=parsed.sha256,
            size_bytes=len(parsed.raw),
            case_count=len(parsed.cases),
        )
        try:
            self.datasets.add(dataset)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            existing = self.datasets.get_by_owner_name(
                owner.id, normalized_name
            )
            if existing is not None and existing.sha256 == parsed.sha256:
                return existing
            raise ConflictException("当前用户已存在同名评测数据集") from exc
        self.db.refresh(dataset)
        return dataset

    def get_owned_dataset(
        self, dataset_id: str, user: User
    ) -> EvaluationDataset:
        dataset = self.datasets.get(dataset_id)
        if dataset is None or (
            user.role != UserRole.ADMIN.value and dataset.owner_id != user.id
        ):
            raise ResourceNotFoundException("评测数据集不存在")
        return dataset

    def submit_run(
        self, request: EvaluationRunCreate, user: User
    ) -> Job:
        dataset = self.get_owned_dataset(str(request.dataset_id), user)
        knowledge_base = self.db.get(
            KnowledgeBase, str(request.knowledge_base_id)
        )
        if knowledge_base is None or (
            user.role != UserRole.ADMIN.value
            and knowledge_base.owner_id != user.id
        ):
            raise ResourceNotFoundException("知识库不存在")
        if (
            not knowledge_base.active_collection_name
            or not knowledge_base.active_embedding_config_hash
        ):
            raise ConflictException("知识库尚无可固定的活动 Collection")

        effective = self.runtime.effective_settings()
        if request.mode == "rag":
            missing = effective.missing_chat_configuration()
            if missing:
                raise ConfigurationException(
                    "RAG 评测不可用，缺少配置：" + ", ".join(missing),
                    status_code=503,
                )
        required_calls = dataset.case_count * (
            2 if request.mode == "rag" else 1
        )
        required_tokens = (
            dataset.case_count * effective.CHAT_MAX_TOKENS
            if request.mode == "rag"
            else 0
        )
        if request.max_calls < required_calls:
            raise ConflictException(
                f"max_calls 至少为 {required_calls}"
            )
        if request.max_generation_tokens < required_tokens:
            raise ConflictException(
                f"max_generation_tokens 至少为 {required_tokens}"
            )

        with self.runtime.vector_write_lock:
            self.db.expire(knowledge_base)
            knowledge_base = self.db.get(
                KnowledgeBase, str(request.knowledge_base_id)
            )
            if knowledge_base is None or (
                user.role != UserRole.ADMIN.value
                and knowledge_base.owner_id != user.id
            ):
                raise ResourceNotFoundException("知识库不存在")
            if (
                not knowledge_base.active_collection_name
                or not knowledge_base.active_embedding_config_hash
            ):
                raise ConflictException("知识库尚无可固定的活动 Collection")

            snapshot = {
                "chat_model": (
                    effective.CHAT_MODEL if request.mode == "rag" else None
                ),
                "chat_temperature": effective.CHAT_TEMPERATURE,
                "chat_max_tokens": effective.CHAT_MAX_TOKENS,
                "chat_timeout_seconds": effective.CHAT_TIMEOUT_SECONDS,
                "chat_max_attempts": effective.CHAT_MAX_ATTEMPTS,
                "rag_context_max_chars": effective.RAG_CONTEXT_MAX_CHARS,
            }
            config_payload = {
                "created_by_id": user.id,
                "dataset_sha256": dataset.sha256,
                "collection_name": knowledge_base.active_collection_name,
                "embedding_config_hash": (
                    knowledge_base.active_embedding_config_hash
                ),
                "mode": request.mode,
                "top_k": request.top_k,
                "score_threshold": request.score_threshold,
                "chat_snapshot": snapshot,
            }
            config_hash = hashlib.sha256(
                json.dumps(
                    config_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            duplicate = self.db.scalar(
                select(Job.id).where(
                    Job.job_type == JobType.RAG_EVALUATION.value,
                    Job.created_by_id == user.id,
                    Job.evaluation_dataset_id == dataset.id,
                    Job.collection_name
                    == knowledge_base.active_collection_name,
                    Job.evaluation_mode == request.mode,
                    Job.evaluation_config_hash == config_hash,
                    Job.status.in_(
                        (
                            JobStatus.QUEUED.value,
                            JobStatus.RUNNING.value,
                            JobStatus.CANCEL_REQUESTED.value,
                        )
                    ),
                )
            )
            if duplicate:
                raise ConflictException("相同配置的评测运行仍在执行")

            evaluation_id = uuid4().hex
            report_path = (
                self.settings.EVALUATION_DIR
                / "reports"
                / f"evaluation-{evaluation_id}.json"
            ).resolve()
            return JobService(self.db).submit(
                job_type=JobType.RAG_EVALUATION,
                created_by_id=user.id,
                resource_type="KNOWLEDGE_BASE",
                resource_id=knowledge_base.id,
                resource_name_snapshot=knowledge_base.name,
                payload={
                    "dataset_path": str(Path(dataset.storage_path).resolve()),
                    "report_path": str(report_path),
                    "case_count": dataset.case_count,
                    "top_k": request.top_k,
                    "score_threshold": request.score_threshold,
                    "max_runtime_seconds": request.max_runtime_seconds,
                    "chat_snapshot": snapshot,
                },
                collection_name=knowledge_base.active_collection_name,
                embedding_config_hash=(
                    knowledge_base.active_embedding_config_hash
                ),
                dataset_sha256=dataset.sha256,
                evaluation_config_hash=config_hash,
                evaluation_dataset_id=dataset.id,
                evaluation_mode=request.mode,
                evaluation_run_name=request.run_name,
                budget_total_calls=request.max_calls,
                budget_total_tokens=request.max_generation_tokens,
                deadline_at=utc_now()
                + timedelta(seconds=request.max_runtime_seconds),
                max_attempts=2,
            )

    def _persist_dataset(self, parsed: ParsedDataset) -> Path:
        dataset_root = (self.settings.EVALUATION_DIR / "datasets").resolve()
        dataset_root.mkdir(parents=True, exist_ok=True)
        storage_path = dataset_root / f"{parsed.sha256}.jsonl"
        if storage_path.exists():
            if (
                hashlib.sha256(storage_path.read_bytes()).hexdigest()
                != parsed.sha256
            ):
                raise ConflictException("数据集存储哈希冲突")
            return storage_path
        partial = storage_path.with_name(
            f".{storage_path.name}.{uuid4().hex}.partial"
        )
        partial.write_bytes(parsed.raw)
        os.replace(partial, storage_path)
        return storage_path


def evaluation_counts(
    db: Session, user: User
) -> tuple[int, int, dict[str, int]]:
    run_filters = [Job.job_type == JobType.RAG_EVALUATION.value]
    dataset_filters = []
    if user.role != UserRole.ADMIN.value:
        run_filters.append(Job.created_by_id == user.id)
        dataset_filters.append(EvaluationDataset.owner_id == user.id)
    run_count = int(
        db.scalar(select(func.count(Job.id)).where(*run_filters)) or 0
    )
    dataset_count = int(
        db.scalar(
            select(func.count(EvaluationDataset.id)).where(*dataset_filters)
        )
        or 0
    )
    rows = db.execute(
        select(Job.status, func.count(Job.id))
        .where(*run_filters)
        .group_by(Job.status)
    ).all()
    return run_count, dataset_count, {
        str(status): int(count) for status, count in rows
    }

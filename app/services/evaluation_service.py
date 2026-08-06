"""Bounded, collection-pinned RAG evaluation without chat-history writes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictException, ValidationException
from app.models import Job, utc_now
from app.repositories.job_repository import JobRepository
from app.schemas.chat import RetrievalAudit
from app.services.rag_service import RagService
from app.services.retrieval_service import RetrievalService
from app.services.runtime_coordinator import RuntimeCoordinator


MAX_DATASET_BYTES = 5 * 1024 * 1024
MAX_CASES = 100
MAX_LINE_BYTES = 64 * 1024
MAX_QUESTION_CHARS = 4000
MAX_EXPECTED_ANSWERS = 20
MAX_EXPECTED_ANSWER_CHARS = 500
MAX_SOURCE_IDS = 100
MAX_TAGS = 20
MAX_TAG_CHARS = 64
_CITATION_LIKE = re.compile(r"\[K[^\]]*\]")
_VALID_CITATION = re.compile(r"\[K([1-9]\d*)\]")


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    sha256: str
    cases: tuple[dict[str, Any], ...]
    raw: bytes


def parse_jsonl_dataset(raw: bytes) -> EvaluationDataset:
    if not raw:
        raise ValidationException("评估 JSONL 不能为空")
    if len(raw) > MAX_DATASET_BYTES:
        raise ValidationException("评估 JSONL 超过 5 MiB")
    cases: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        if len(raw_line) > MAX_LINE_BYTES:
            raise ValidationException(f"第 {line_number} 行超过 64 KiB")
        if not raw_line.strip():
            raise ValidationException(f"第 {line_number} 行不能为空")
        try:
            item = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationException(f"第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(item, dict):
            raise ValidationException(f"第 {line_number} 行必须是 JSON 对象")
        question = item.get("question")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= MAX_QUESTION_CHARS:
            raise ValidationException(f"第 {line_number} 行 question 长度无效")
        expected = item.get("expected_answer")
        if (
            not isinstance(expected, list)
            or not 1 <= len(expected) <= MAX_EXPECTED_ANSWERS
            or any(
                not isinstance(value, str)
                or not 1 <= len(value.strip()) <= MAX_EXPECTED_ANSWER_CHARS
                for value in expected
            )
        ):
            raise ValidationException(
                f"第 {line_number} 行 expected_answer 必须含 1–20 个、每项最多 500 字符"
            )
        source_ids = item.get("source_ids", [])
        if (
            not isinstance(source_ids, list)
            or len(source_ids) > MAX_SOURCE_IDS
            or any(not isinstance(value, str) or not value for value in source_ids)
        ):
            raise ValidationException(f"第 {line_number} 行 source_ids 无效")
        tags = item.get("tags", [])
        if (
            not isinstance(tags, list)
            or len(tags) > MAX_TAGS
            or any(
                not isinstance(value, str)
                or not 1 <= len(value) <= MAX_TAG_CHARS
                for value in tags
            )
        ):
            raise ValidationException(f"第 {line_number} 行 tags 无效")
        cases.append(
            {
                "question": question.strip(),
                "expected_answer": expected,
                "source_ids": source_ids,
                "tags": tags,
            }
        )
        if len(cases) > MAX_CASES:
            raise ValidationException("评估案例数超过 100")
    return EvaluationDataset(
        sha256=hashlib.sha256(raw).hexdigest(),
        cases=tuple(cases),
        raw=raw,
    )


class EvaluationService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        runtime: RuntimeCoordinator,
    ) -> None:
        self.db = db
        self.settings = settings
        self.runtime = runtime

    def run(self, job: Job, checkpoint: object) -> dict[str, Any]:
        evaluation_started = datetime.now(timezone.utc)
        evaluation_clock = time.perf_counter()
        mode = job.evaluation_mode or "rag"
        if mode not in {"retrieval", "rag"}:
            raise ConflictException("评测 Job 的运行模式无效")
        dataset_path = Path(str(job.payload["dataset_path"])).resolve()
        dataset = parse_jsonl_dataset(dataset_path.read_bytes())
        if dataset.sha256 != job.dataset_sha256:
            raise ConflictException("评估数据集哈希与 Job 固定值不一致")
        if not job.collection_name or not job.embedding_config_hash:
            raise ConflictException("评估 Job 缺少固定 Collection 或配置哈希")
        top_k = int(job.payload["top_k"])
        threshold = job.payload.get("score_threshold")
        report_path = Path(str(job.payload["report_path"])).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_name(
            f".{report_path.name}.attempt-{job.attempt}.partial"
        )
        if temporary.exists():
            abandoned = temporary.with_name(
                f"{temporary.name}.abandoned-{job.id}"
            )
            if abandoned.exists():
                raise ConflictException("评估 attempt 临时文件隔离目标已存在")
            os.replace(temporary, abandoned)

        retrieval = RetrievalService(self.db, self.settings, self.runtime)
        rag = RagService(retrieval, self.settings)
        calls_per_case = 2 if mode == "rag" else 1
        tokens_per_case = (
            self.settings.CHAT_MAX_TOKENS if mode == "rag" else 0
        )
        case_results: list[dict[str, Any]] = []
        for index, case in enumerate(dataset.cases):
            case_clock = time.perf_counter()
            retrieval_seconds = 0.0
            generation_seconds = 0.0
            retrieval_metrics = {
                "hit_at_k": None,
                "recall_at_k": None,
                "reciprocal_rank": None,
                "retrieved_file_ids": [],
            }
            citation_metrics = {
                "format_valid": None,
                "citation_count": None,
                "out_of_range_count": None,
                "source_hit_rate": None,
            }
            answer_point_recall: float | None = None
            checkpoint(
                f"EVALUATION_CASE_{index}",
                int(index * 90 / max(1, len(dataset.cases))),
            )
            if job.deadline_at is not None and utc_now() >= job.deadline_at:
                raise ConflictException("评估超过最长运行时间预算")
            self._reserve_budget(
                job.id, calls=calls_per_case, tokens=tokens_per_case
            )
            try:
                retrieval_clock = time.perf_counter()
                try:
                    chunks = retrieval.retrieve_chunks_from_collection(
                        knowledge_base_id=str(job.resource_id),
                        collection_name=job.collection_name,
                        embedding_config_hash=job.embedding_config_hash,
                        query=case["question"],
                        top_k=top_k,
                        score_threshold=threshold,
                    )
                finally:
                    retrieval_seconds = max(
                        0.0, time.perf_counter() - retrieval_clock
                    )
                retrieval_metrics = _retrieval_case_metrics(
                    chunks, case["source_ids"]
                )
                if mode == "retrieval":
                    answer = None
                    sources = [
                        {
                            "rank": rank,
                            "file_id": str(chunk.file_id),
                            "file_name": chunk.file_name,
                            "chunk_id": chunk.chunk_id,
                            "content": chunk.content,
                            "score": chunk.score,
                            "metadata": chunk.metadata,
                        }
                        for rank, chunk in enumerate(chunks, start=1)
                    ]
                else:
                    candidates = rag._prepare_candidates(chunks)
                    context = rag.build_context(
                        candidates, self.settings.RAG_CONTEXT_MAX_CHARS
                    )
                    if not context.sources:
                        answer = ""
                        sources = []
                        citation_metrics = {
                            "format_valid": True,
                            "citation_count": 0,
                            "out_of_range_count": 0,
                            "source_hit_rate": (
                                None if not case["source_ids"] else 0.0
                            ),
                        }
                        answer_point_recall = 0.0
                    else:
                        runtime_config = rag._chat_runtime_config()
                        client = rag._create_chat_client(runtime_config)
                        calls = 0

                        def before_generation_call() -> None:
                            nonlocal calls
                            calls += 1
                            if calls > 1:
                                raise ConflictException(
                                    "单案例 Generation 调用超过一次"
                                )

                        generation_clock = time.perf_counter()
                        try:
                            raw_answer = client.generate(
                                rag._build_messages(
                                    case["question"],
                                    context,
                                    RetrievalAudit(),
                                ),
                                before_generation_call=before_generation_call,
                            )
                        finally:
                            generation_seconds = max(
                                0.0,
                                time.perf_counter() - generation_clock,
                            )
                        citation_metrics = _citation_case_metrics(
                            raw_answer,
                            len(context.sources),
                            case["source_ids"],
                            [
                                str(source.chunk.file_id)
                                for source in context.sources
                            ],
                        )
                        response = rag._build_response(raw_answer, context)
                        answer = response.answer
                        sources = [
                            source.model_dump(mode="json")
                            for source in response.sources
                        ]
                        normalized_answer = answer.casefold()
                        expected_points = case["expected_answer"]
                        answer_point_recall = sum(
                            point.casefold() in normalized_answer
                            for point in expected_points
                        ) / len(expected_points)
                result = {
                    "index": index,
                    **case,
                    "answer": answer,
                    "sources": sources,
                    "error": None,
                }
            except Exception as exc:
                result = {
                    "index": index,
                    **case,
                    "answer": None,
                    "sources": [],
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc)[:1000],
                    },
                }
            finally:
                self._consume_budget(
                    job.id,
                    calls=calls_per_case,
                    tokens=tokens_per_case,
                )
            result["retrieval_metrics"] = retrieval_metrics
            result["citation_metrics"] = citation_metrics
            result["answer_metrics"] = {
                "success": (
                    bool(result.get("answer")) if mode == "rag" else None
                ),
                "expected_answer_point_recall": answer_point_recall,
            }
            result["timing_seconds"] = {
                "retrieval": retrieval_seconds,
                "generation": generation_seconds,
                "end_to_end": max(
                    0.0, time.perf_counter() - case_clock
                ),
            }
            case_results.append(result)

        evaluation_finished = datetime.now(timezone.utc)
        summary = _aggregate_metrics(case_results, mode=mode)
        failure_count = sum(
            item["error"] is not None for item in case_results
        )
        outcome = "PARTIAL_SUCCESS" if failure_count else "SUCCESS"
        report = {
            "format": "local-rag-evaluation-report",
            "format_version": 2,
            "job_id": job.id,
            "dataset_id": job.evaluation_dataset_id,
            "dataset_sha256": dataset.sha256,
            "dataset_case_count": len(dataset.cases),
            "run_name": job.evaluation_run_name or "历史评测",
            "mode": mode,
            "knowledge_base_id": job.resource_id,
            "knowledge_base_name": job.resource_name_snapshot,
            "collection_name": job.collection_name,
            "embedding_config_hash": job.embedding_config_hash,
            "evaluation_config_hash": job.evaluation_config_hash,
            "started_at": evaluation_started.isoformat(),
            "finished_at": evaluation_finished.isoformat(),
            "duration_seconds": max(
                0.0, time.perf_counter() - evaluation_clock
            ),
            "generation_model": (
                self.settings.CHAT_MODEL if mode == "rag" else None
            ),
            "top_k": top_k,
            "score_threshold": threshold,
            "case_count": len(case_results),
            "success_count": sum(
                item["error"] is None for item in case_results
            ),
            "failure_count": failure_count,
            "outcome": outcome,
            "metrics": summary,
            "cases": case_results,
        }
        report_bytes = json.dumps(
            report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        temporary.write_bytes(report_bytes)
        os.replace(temporary, report_path)
        digest = hashlib.sha256(report_bytes).hexdigest()
        current = self.db.get(Job, job.id)
        if current is None:
            raise ConflictException("评估 Job 已不存在")
        current.report_path = str(report_path)
        current.report_sha256 = digest
        self.db.commit()
        return {
            "report_path": str(report_path),
            "report_sha256": digest,
            "outcome": outcome,
            "success_count": len(case_results) - failure_count,
            "failure_count": failure_count,
        }

    def _reserve_budget(self, job_id: str, *, calls: int, tokens: int) -> None:
        repository = JobRepository(self.db)
        if not repository.reserve_evaluation_budget(
            job_id=job_id, calls=calls, tokens=tokens
        ):
            self.db.rollback()
            raise ConflictException("评估调用或生成 token 预算不足")
        self.db.commit()

    def _consume_budget(self, job_id: str, *, calls: int, tokens: int) -> None:
        if not JobRepository(self.db).consume_evaluation_budget(
            job_id=job_id, calls=calls, tokens=tokens
        ):
            self.db.rollback()
            raise ConflictException("评估预算消费状态不一致")
        self.db.commit()


def _retrieval_case_metrics(
    chunks: list[object], expected_source_ids: list[str]
) -> dict[str, Any]:
    retrieved: list[str] = []
    for chunk in chunks:
        file_id = str(chunk.file_id)
        if file_id not in retrieved:
            retrieved.append(file_id)
    expected = list(dict.fromkeys(expected_source_ids))
    if not expected:
        return {
            "hit_at_k": None,
            "recall_at_k": None,
            "reciprocal_rank": None,
            "retrieved_file_ids": retrieved,
        }
    expected_set = set(expected)
    matched = expected_set.intersection(retrieved)
    first_rank = next(
        (
            index
            for index, file_id in enumerate(retrieved, start=1)
            if file_id in expected_set
        ),
        None,
    )
    return {
        "hit_at_k": bool(matched),
        "recall_at_k": len(matched) / len(expected_set),
        "reciprocal_rank": 0.0 if first_rank is None else 1.0 / first_rank,
        "retrieved_file_ids": retrieved,
    }


def _citation_case_metrics(
    raw_answer: str,
    source_count: int,
    expected_source_ids: list[str],
    context_source_ids: list[str],
) -> dict[str, Any]:
    citation_like = _CITATION_LIKE.findall(raw_answer)
    valid_matches = list(_VALID_CITATION.finditer(raw_answer))
    numbers = [int(match.group(1)) for match in valid_matches]
    out_of_range = sum(number > source_count for number in numbers)
    cited_file_ids = {
        context_source_ids[number - 1]
        for number in numbers
        if 1 <= number <= source_count
    }
    expected = set(expected_source_ids)
    source_hit_rate = (
        None
        if not expected
        else len(cited_file_ids.intersection(expected)) / len(expected)
    )
    return {
        "format_valid": bool(citation_like)
        and len(citation_like) == len(valid_matches),
        "citation_count": len(numbers),
        "out_of_range_count": out_of_range,
        "source_hit_rate": source_hit_rate,
    }


def _aggregate_metrics(
    cases: list[dict[str, Any]],
    *,
    mode: str = "rag",
) -> dict[str, Any]:
    total = len(cases)
    retrieval_cases = [
        item["retrieval_metrics"]
        for item in cases
        if item["retrieval_metrics"]["hit_at_k"] is not None
    ]
    source_hit_cases = [
        item["citation_metrics"]["source_hit_rate"]
        for item in cases
        if item["citation_metrics"]["source_hit_rate"] is not None
    ]
    citation_count = sum(
        int(item["citation_metrics"]["citation_count"] or 0)
        for item in cases
    )
    out_of_range = sum(
        int(item["citation_metrics"]["out_of_range_count"] or 0)
        for item in cases
    )
    failures = Counter(
        item["error"]["type"]
        for item in cases
        if item["error"] is not None
    )

    def average(values: list[float]) -> float | None:
        return None if not values else sum(values) / len(values)

    return {
        "retrieval": {
            "evaluated_cases": len(retrieval_cases),
            "hit_at_k": average(
                [
                    float(item["hit_at_k"])
                    for item in retrieval_cases
                ]
            ),
            "recall_at_k": average(
                [float(item["recall_at_k"]) for item in retrieval_cases]
            ),
            "mrr": average(
                [
                    float(item["reciprocal_rank"])
                    for item in retrieval_cases
                ]
            ),
            "average_latency_seconds": average(
                [
                    float(item["timing_seconds"]["retrieval"])
                    for item in cases
                ]
            ),
        },
        "generation_and_citations": None
        if mode != "rag"
        else {
            "answer_success_rate": (
                0.0
                if not total
                else sum(
                    item["answer_metrics"]["success"] for item in cases
                )
                / total
            ),
            "expected_answer_point_recall": average(
                [
                    float(
                        item["answer_metrics"][
                            "expected_answer_point_recall"
                        ]
                    )
                    for item in cases
                ]
            ),
            "citation_format_valid_rate": (
                0.0
                if not total
                else sum(
                    item["citation_metrics"]["format_valid"]
                    for item in cases
                )
                / total
            ),
            "citation_out_of_range_rate": (
                0.0 if not citation_count else out_of_range / citation_count
            ),
            "citation_source_hit_rate": average(
                [float(value) for value in source_hit_cases]
            ),
            "average_generation_latency_seconds": average(
                [
                    float(item["timing_seconds"]["generation"])
                    for item in cases
                ]
            ),
            "average_end_to_end_seconds": average(
                [
                    float(item["timing_seconds"]["end_to_end"])
                    for item in cases
                ]
            ),
        },
        "failure_types": dict(sorted(failures.items())),
    }

"""Bounded JSONL evaluation and fixed-Collection integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.exceptions import ValidationException
from app.models import ChatMessage, ChatSession, Job, KnowledgeBase
from app.services.evaluation_service import (
    MAX_DATASET_BYTES,
    MAX_LINE_BYTES,
    parse_jsonl_dataset,
)
from app.services.rag_service import RagService
from tests.conftest import wait_for_job
from tests.fakes import FakeEmbedding


def _line(**overrides: object) -> bytes:
    item: dict[str, object] = {
        "question": "What is stable?",
        "expected_answer": ["stable retrieval text"],
        "source_ids": [],
        "tags": [],
    }
    item.update(overrides)
    return json.dumps(item, ensure_ascii=False).encode("utf-8")


def test_jsonl_accepts_documented_upper_case_count() -> None:
    raw = b"\n".join(_line(question=f"question {index}") for index in range(100))
    dataset = parse_jsonl_dataset(raw)
    assert len(dataset.cases) == 100
    assert len(dataset.sha256) == 64


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * (MAX_DATASET_BYTES + 1),
        b"x" * (MAX_LINE_BYTES + 1),
        b"\n".join(_line(question=f"q{index}") for index in range(101)),
        _line(question="q" * 4001),
        _line(expected_answer=[]),
        _line(expected_answer=["a"] * 21),
        _line(expected_answer=["a" * 501]),
        _line(source_ids=[str(index) for index in range(101)]),
        _line(tags=["tag"] * 21),
        _line(tags=["t" * 65]),
    ],
    ids=[
        "file-bytes",
        "line-bytes",
        "case-count",
        "question-length",
        "missing-answer",
        "answer-count",
        "answer-length",
        "source-count",
        "tag-count",
        "tag-length",
    ],
)
def test_jsonl_rejects_every_documented_resource_limit(raw: bytes) -> None:
    with pytest.raises(ValidationException):
        parse_jsonl_dataset(raw)


def test_evaluation_uses_pinned_collection_and_writes_no_chat_history(
    client,
    app,
    test_settings,
    monkeypatch,
) -> None:
    fake_embedding = FakeEmbedding()
    vector_store = app.state.rag_runtime.vector_store
    vector_store._embedding_factory = lambda _: fake_embedding
    vector_store._embedding_cache.clear()
    test_settings.CHAT_MODEL = "fake-model"
    test_settings.DASHSCOPE_API_KEY = SecretStr("fake-api-key")

    class FixedChatClient:
        def generate(self, _messages, *, before_generation_call):
            before_generation_call()
            return "Grounded answer [K1]"

    monkeypatch.setattr(
        RagService,
        "_create_chat_client",
        lambda _self, _config: FixedChatClient(),
    )

    created = client.post(
        "/api/knowledge-bases", json={"name": "evaluation-pinned"}
    )
    knowledge_base_id = created.json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={
            "file": (
                "evaluation.txt",
                b"stable retrieval text",
                "text/plain",
            )
        },
    ).json()["data"]
    process_job = wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )
    assert process_job["status"] == "SUCCEEDED"

    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        pinned_collection = knowledge_base.active_collection_name
        session_count_before = db.scalar(select(func.count(ChatSession.id)))
        message_count_before = db.scalar(select(func.count(ChatMessage.id)))

    evaluation = client.post(
        "/api/evaluations",
        data={
            "knowledge_base_id": knowledge_base_id,
            "top_k": "4",
            "max_calls": "2",
            "max_generation_tokens": str(test_settings.CHAT_MAX_TOKENS),
            "max_runtime_seconds": "60",
        },
        files={
            "dataset_file": (
                "dataset.jsonl",
                _line(
                    expected_answer=["Grounded answer"],
                    source_ids=[uploaded["id"]],
                ),
                "application/x-ndjson",
            )
        },
    )
    evaluation_job = wait_for_job(client, evaluation)
    assert evaluation_job["status"] == "SUCCEEDED"
    assert evaluation_job["collection_name"] == pinned_collection
    assert evaluation_job["budget_reserved_calls"] == 2
    assert evaluation_job["budget_used_calls"] == 2
    public_report = client.get(
        f"/api/evaluations/{evaluation_job['id']}/report"
    )
    assert public_report.status_code == 200
    assert (
        public_report.json()["data"]["collection_name"]
        == pinned_collection
    )

    with app.state.session_factory() as db:
        persisted_job = db.get(Job, evaluation_job["id"])
        assert persisted_job is not None
        report_path = Path(str(persisted_job.report_path))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["collection_name"] == pinned_collection
        assert report["metrics"]["retrieval"]["hit_at_k"] == 1.0
        assert report["metrics"]["retrieval"]["recall_at_k"] == 1.0
        assert report["metrics"]["retrieval"]["mrr"] == 1.0
        assert (
            report["metrics"]["generation_and_citations"][
                "citation_format_valid_rate"
            ]
            == 1.0
        )
        assert (
            report["metrics"]["generation_and_citations"][
                "expected_answer_point_recall"
            ]
            == 1.0
        )
        assert report["metrics"]["failure_types"] == {}
        assert db.scalar(select(func.count(ChatSession.id))) == session_count_before
        assert db.scalar(select(func.count(ChatMessage.id))) == message_count_before

    rebuild_job = wait_for_job(
        client,
        client.post(f"/api/knowledge-bases/{knowledge_base_id}/rebuild"),
    )
    assert rebuild_job["status"] == "SUCCEEDED"
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        assert knowledge_base.active_collection_name != pinned_collection
    assert json.loads(report_path.read_text(encoding="utf-8"))[
        "collection_name"
    ] == pinned_collection


def test_retrieval_evaluation_dataset_history_summary_and_cases(
    client,
    app,
) -> None:
    fake_embedding = FakeEmbedding()
    vector_store = app.state.rag_runtime.vector_store
    vector_store._embedding_factory = lambda _: fake_embedding
    vector_store._embedding_cache.clear()

    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "retrieval-evaluation"}
    ).json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("source.txt", b"stable retrieval text", "text/plain")},
    ).json()["data"]
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == "SUCCEEDED"

    dataset_response = client.post(
        "/api/evaluation-datasets",
        data={"name": "retrieval baseline", "description": "deterministic"},
        files={
            "dataset_file": (
                "retrieval.jsonl",
                _line(source_ids=[uploaded["id"]]),
                "application/x-ndjson",
            )
        },
    )
    assert dataset_response.status_code == 201, dataset_response.text
    dataset = dataset_response.json()["data"]
    listed = client.get("/api/evaluation-datasets?limit=10&offset=0")
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["items"][0]["sha256"] == dataset["sha256"]

    submission = client.post(
        "/api/evaluations/runs",
        json={
            "dataset_id": dataset["id"],
            "knowledge_base_id": knowledge_base_id,
            "run_name": "retrieval only",
            "mode": "retrieval",
            "top_k": 4,
            "score_threshold": None,
            "max_calls": 1,
            "max_generation_tokens": 0,
            "max_runtime_seconds": 60,
        },
    )
    assert submission.status_code == 202, submission.text
    run_id = submission.json()["data"]["job"]["id"]
    terminal = wait_for_job(
        client,
        type(
            "Submission",
            (),
            {
                "status_code": 202,
                "text": "",
                "json": lambda _self: {"data": {"id": run_id}},
            },
        )(),
    )
    assert terminal["status"] == "SUCCEEDED"
    assert terminal["evaluation_mode"] == "retrieval"
    assert terminal["budget_used_calls"] == 1
    assert terminal["budget_used_tokens"] == 0

    detail = client.get(f"/api/evaluations/{run_id}")
    assert detail.status_code == 200
    run = detail.json()["data"]
    assert run["outcome"] == "SUCCESS"
    assert run["metrics"]["retrieval"]["hit_at_k"] == 1.0
    assert run["metrics"]["generation_and_citations"] is None
    cases = client.get(f"/api/evaluations/{run_id}/cases")
    assert cases.status_code == 200
    assert cases.json()["data"]["total"] == 1
    assert cases.json()["data"]["items"][0]["answer"] is None
    assert cases.json()["data"]["items"][0]["sources"][0]["content"]
    failed = client.get(
        f"/api/evaluations/{run_id}/cases?failed_only=true"
    )
    assert failed.json()["data"]["total"] == 0
    summary = client.get("/api/evaluations/summary").json()["data"]
    assert summary["dataset_count"] == 1
    assert summary["run_count"] == 1
    assert summary["status_counts"]["SUCCEEDED"] == 1


def test_rag_run_rejects_missing_chat_configuration(client, app) -> None:
    vector_store = app.state.rag_runtime.vector_store
    vector_store._embedding_factory = lambda _: FakeEmbedding()
    vector_store._embedding_cache.clear()
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "rag-config-required"}
    ).json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("source.txt", b"indexed source", "text/plain")},
    ).json()["data"]
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == "SUCCEEDED"
    dataset = client.post(
        "/api/evaluation-datasets",
        data={"name": "rag dataset"},
        files={
            "dataset_file": (
                "rag.jsonl",
                _line(),
                "application/x-ndjson",
            )
        },
    ).json()["data"]
    response = client.post(
        "/api/evaluations/runs",
        json={
            "dataset_id": dataset["id"],
            "knowledge_base_id": knowledge_base_id,
            "run_name": "requires chat",
            "mode": "rag",
        },
    )
    assert response.status_code == 503
    assert "CHAT_MODEL" in response.json()["message"]

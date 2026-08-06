"""Direct Real retrieval API contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document

from app.models import KnowledgeBase
from app.services.vector_store_service import VectorSearchResult


def test_retrieval_requires_active_index_and_returns_real_content(
    client, app, monkeypatch
) -> None:
    created = client.post(
        "/api/knowledge-bases", json={"name": "direct-retrieval"}
    ).json()["data"]
    knowledge_base_id = created["id"]
    request = {
        "knowledge_base_id": knowledge_base_id,
        "query": "真实查询",
        "top_k": 5,
        "score_threshold": 0.2,
    }
    missing = client.post("/api/retrieval", json=request)
    assert missing.status_code == 409

    config_hash = "b" * 64
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        knowledge_base.active_collection_name = "direct_collection"
        knowledge_base.active_embedding_config_hash = config_hash
        db.commit()

    store = app.state.rag_runtime.vector_store
    monkeypatch.setattr(
        store,
        "get_collection",
        lambda *_args, **_kwargs: SimpleNamespace(count=lambda: 1),
    )
    file_id = uuid4()
    captured: list[tuple[str, int, float | None]] = []

    def search(query, top_k=5, score_threshold=None, **_kwargs):
        captured.append((query, top_k, score_threshold))
        return [
            VectorSearchResult(
                vector_id="real-vector",
                document=Document(
                    page_content="来自 Chroma 的完整分块正文",
                    metadata={
                        "knowledge_base_id": knowledge_base_id,
                        "embedding_config_hash": config_hash,
                        "file_id": str(file_id),
                        "file_name": "source.txt",
                        "file_type": ".txt",
                        "chunk_id": "chunk-real",
                        "chunk_index": 2,
                        "processing_job_id": "must-not-leak",
                    },
                ),
                distance=0.08,
                score=0.92,
            )
        ]

    monkeypatch.setattr(store, "similarity_search", search)
    response = client.post("/api/retrieval", json=request)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["result_count"] == 1
    assert data["results"][0] == {
        "rank": 1,
        "score": 0.92,
        "file_id": str(file_id),
        "file_name": "source.txt",
        "chunk_id": "chunk-real",
        "content": "来自 Chroma 的完整分块正文",
        "metadata": {"file_type": ".txt", "chunk_index": 2},
    }
    assert captured == [("真实查询", 5, 0.2)]

    request["score_threshold"] = None
    no_threshold = client.post("/api/retrieval", json=request)
    assert no_threshold.status_code == 200
    assert captured[-1] == ("真实查询", 5, None)


def test_retrieval_validates_public_parameters(client) -> None:
    response = client.post(
        "/api/retrieval",
        json={
            "knowledge_base_id": str(uuid4()),
            "query": "",
            "top_k": 101,
            "score_threshold": -2,
        },
    )
    assert response.status_code == 422

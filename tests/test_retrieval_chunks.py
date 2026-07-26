"""Full-chunk retrieval and threshold compatibility tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document

from app.models import KnowledgeBase
from app.services.retrieval_service import RetrievalService
from app.services.vector_store_service import VectorSearchResult


def test_retrieve_chunks_preserves_full_content_and_threshold_semantics(
    app,
    client,
    test_settings,
    monkeypatch,
) -> None:
    created = client.post(
        "/api/knowledge-bases",
        json={"name": "retrieval-full-content"},
    )
    kb_id = created.json()["data"]["id"]
    config_hash = "a" * 64
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, kb_id)
        assert knowledge_base is not None
        knowledge_base.active_collection_name = "test_collection"
        knowledge_base.active_embedding_config_hash = config_hash
        db.commit()

    full_content = "完整内容" + "甲" * 1500
    file_id = uuid4()
    captured_thresholds: list[float | None] = []
    store = app.state.rag_runtime.vector_store
    monkeypatch.setattr(
        store,
        "get_collection",
        lambda *_args, **_kwargs: SimpleNamespace(count=lambda: 1),
    )

    def fake_search(
        _query,
        _top_k=5,
        score_threshold=None,
        **_kwargs,
    ):
        captured_thresholds.append(score_threshold)
        return [
            VectorSearchResult(
                vector_id="vector-1",
                document=Document(
                    page_content=full_content,
                    metadata={
                        "knowledge_base_id": kb_id,
                        "embedding_config_hash": config_hash,
                        "file_id": str(file_id),
                        "file_name": "full.txt",
                        "chunk_id": "chunk-1",
                    },
                ),
                distance=0.1,
                score=0.9,
            )
        ]

    monkeypatch.setattr(store, "similarity_search", fake_search)
    settings_with_threshold = test_settings.model_copy(
        update={"RETRIEVAL_SCORE_THRESHOLD": 0.75}
    )
    with app.state.session_factory() as db:
        service = RetrievalService(
            db,
            settings_with_threshold,
            app.state.rag_runtime,
        )
        omitted = service.retrieve_chunks(kb_id, "query")
        explicit_none = service.retrieve_chunks(
            kb_id,
            "query",
            score_threshold=None,
        )
        explicit_value = service.retrieve_chunks(
            kb_id,
            "query",
            score_threshold=0.25,
        )
        public = service.retrieve(kb_id, "query")
        no_threshold = RetrievalService(
            db,
            test_settings,
            app.state.rag_runtime,
        ).retrieve_chunks(kb_id, "query")

    assert omitted[0].content == full_content
    assert len(omitted[0].content_preview) <= 1000
    assert omitted[0].content_preview != omitted[0].content
    assert public[0] == omitted[0].to_source_reference()
    assert explicit_none
    assert explicit_value
    assert no_threshold
    assert captured_thresholds == [0.75, 0.75, 0.25, 0.75, None]

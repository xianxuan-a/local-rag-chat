"""Real synchronous RAG API wiring with fake local model providers."""

from __future__ import annotations

from http import HTTPStatus

from dashscope.api_entities.dashscope_response import GenerationResponse
from pydantic import SecretStr

from tests.fakes import FakeEmbedding
from tests.conftest import wait_for_job


def _success_response(content: str) -> GenerationResponse:
    raw = GenerationResponse(
        status_code=HTTPStatus.OK,
        output={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    }
                }
            ]
        },
    )
    return GenerationResponse.from_api_response(raw)


def test_chat_api_runs_real_retrieval_and_rag_pipeline(
    client,
    app,
    test_settings,
    monkeypatch,
) -> None:
    fake_embedding = FakeEmbedding()
    vector_store = app.state.rag_runtime.vector_store
    vector_store._embedding_factory = lambda _config: fake_embedding
    vector_store._embedding_cache.clear()
    test_settings.CHAT_MODEL = "test-chat-model"
    test_settings.DASHSCOPE_API_KEY = SecretStr("test-key")
    generation_calls = 0

    def fake_generation(**_kwargs):
        nonlocal generation_calls
        generation_calls += 1
        return _success_response("测试回答 [K1]")

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_generation,
    )
    created = client.post(
        "/api/knowledge-bases",
        json={"name": "rag-api-kb"},
    )
    knowledge_base_id = created.json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={
            "file": (
                "rag.txt",
                "这是完整的 RAG 测试正文。".encode("utf-8"),
                "text/plain",
            )
        },
    )
    file_id = uploaded.json()["data"]["id"]
    assert wait_for_job(
        client, client.post(f"/api/files/{file_id}/process")
    )["status"] == "SUCCEEDED"

    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": knowledge_base_id,
            "question": "测试正文是什么？",
            "top_k": 4,
            "mode": "hybrid",
        },
    )

    assert response.status_code == 200
    response_data = response.json()["data"]
    assert response_data["answer"] == "测试回答 [K1]"
    assert response_data["requested_mode"] == "hybrid"
    assert response_data["effective_mode"] == "knowledge_only"
    assert response_data["web_search_status"] == "blocked_by_policy"
    assert response_data["fallback_reason"] == "global_web_search_disabled"
    assert response_data["sources"][0]["file_id"] == file_id
    assert response_data["sources"][0]["content_preview"].startswith(
        "这是完整的 RAG 测试正文"
    )
    history = client.get(
        f"/api/sessions/{response_data['session_id']}/messages",
        params={"knowledge_base_id": knowledge_base_id},
    )
    assert history.status_code == 200
    messages = history.json()["data"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "测试正文是什么？"
    assert messages[1]["content"] == "测试回答 [K1]"
    assert messages[1]["requested_mode"] == "hybrid"
    assert messages[1]["effective_mode"] == "knowledge_only"
    assert messages[1]["references"][0]["file_id"] == file_id
    assert generation_calls == 1
    assert fake_embedding.document_calls == 1
    assert fake_embedding.query_calls == 1

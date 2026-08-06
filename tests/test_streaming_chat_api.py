"""True NDJSON streaming chat and persistence integration tests."""

from __future__ import annotations

from http import HTTPStatus
import json

import anyio
from dashscope.api_entities.dashscope_response import GenerationResponse
from dashscope.common.error import RequestFailure
from pydantic import SecretStr

from app.api.chat import stream_chat
from app.models import User
from app.schemas.chat import ChatRequest
from tests.fakes import FakeEmbedding
from tests.conftest import wait_for_job


def _stream_response(content: str) -> GenerationResponse:
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


def _prepare_indexed_knowledge_base(
    client,
    app,
    test_settings,
    name: str,
) -> tuple[str, str]:
    fake_embedding = FakeEmbedding()
    vector_store = app.state.rag_runtime.vector_store
    vector_store._embedding_factory = lambda _config: fake_embedding
    vector_store._embedding_cache.clear()
    test_settings.CHAT_MODEL = "test-chat-model"
    test_settings.DASHSCOPE_API_KEY = SecretStr("test-key")
    created = client.post("/api/knowledge-bases", json={"name": name})
    knowledge_base_id = created.json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={
            "file": (
                "stream.txt",
                "这是流式 RAG 的真实检索正文。".encode("utf-8"),
                "text/plain",
            )
        },
    )
    file_id = uploaded.json()["data"]["id"]
    assert wait_for_job(
        client, client.post(f"/api/files/{file_id}/process")
    )["status"] == "SUCCEEDED"
    return knowledge_base_id, file_id


def _parse_events(response) -> list[dict]:
    return [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]


def test_streaming_chat_emits_real_deltas_sources_and_done(
    client,
    app,
    test_settings,
    monkeypatch,
) -> None:
    knowledge_base_id, file_id = _prepare_indexed_knowledge_base(
        client,
        app,
        test_settings,
        "stream-success",
    )
    calls = []

    def fake_generation(**kwargs):
        calls.append(kwargs)
        return iter(
            [
                _stream_response("流式"),
                _stream_response("回答 [K1]"),
            ]
        )

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_generation,
    )
    created_session = client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": "流式会话",
        },
    ).json()["data"]

    response = client.post(
        "/api/chat/stream",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": created_session["id"],
            "question": "正文是什么？",
            "top_k": 4,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-ndjson"
    )
    events = _parse_events(response)
    assert [event["type"] for event in events] == [
        "start",
        "retrieval",
        "delta",
        "sources",
        "done",
    ]
    assert "".join(
        event["content"] for event in events if event["type"] == "delta"
    ) == "流式回答 [K1]"
    assert events[-2]["sources"][0]["file_id"] == file_id
    assert calls[0]["stream"] is True
    assert calls[0]["incremental_output"] is True

    history = client.get(
        f"/api/sessions/{created_session['id']}/messages",
        params={"knowledge_base_id": knowledge_base_id},
    ).json()["data"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[1]["content"] == "流式回答 [K1]"
    assert history[1]["references"][0]["file_id"] == file_id


def test_midstream_provider_failure_emits_error_and_saves_partial_state(
    client,
    app,
    test_settings,
    monkeypatch,
) -> None:
    knowledge_base_id, _ = _prepare_indexed_knowledge_base(
        client,
        app,
        test_settings,
        "stream-failure",
    )
    created_session = client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": "失败会话",
        },
    ).json()["data"]

    def broken_stream():
        yield _stream_response("部分回答")
        raise RequestFailure(
            request_id="stream-request",
            message="provider unavailable",
            name="ServiceUnavailable",
            http_code=503,
        )

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: broken_stream(),
    )
    response = client.post(
        "/api/chat/stream",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": created_session["id"],
            "question": "触发中途失败",
            "top_k": 4,
        },
    )

    events = _parse_events(response)
    assert [event["type"] for event in events] == [
        "start",
        "retrieval",
        "error",
    ]
    assert events[-1]["code"] == 503
    history = client.get(
        f"/api/sessions/{created_session['id']}/messages",
        params={"knowledge_base_id": knowledge_base_id},
    )
    messages = history.json()["data"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == ""
    assert messages[1]["status"] == "failed"
    assert messages[1]["error_code"] == "MODEL_UNAVAILABLE"


def test_streaming_chat_rejects_cross_knowledge_base_session(
    client,
) -> None:
    first_kb = client.post(
        "/api/knowledge-bases",
        json={"name": "stream-owner-one"},
    ).json()["data"]["id"]
    second_kb = client.post(
        "/api/knowledge-bases",
        json={"name": "stream-owner-two"},
    ).json()["data"]["id"]
    chat_session = client.post(
        "/api/sessions",
        json={"knowledge_base_id": first_kb, "title": "owner"},
    ).json()["data"]

    response = client.post(
        "/api/chat/stream",
        json={
            "knowledge_base_id": second_kb,
            "session_id": chat_session["id"],
            "question": "跨库",
            "top_k": 4,
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == 404


def test_client_disconnect_closes_provider_and_saves_cancelled_partial_answer(
    client,
    app,
    test_settings,
    monkeypatch,
) -> None:
    knowledge_base_id, _ = _prepare_indexed_knowledge_base(
        client,
        app,
        test_settings,
        "stream-disconnect",
    )
    created_session = client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": "断开会话",
        },
    ).json()["data"]

    class ProviderIterator:
        def __init__(self) -> None:
            self.closed = False
            self.responses = iter(
                [
                    _stream_response("第一段 [K1]"),
                    _stream_response("不会完成"),
                ]
            )

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.responses)

        def close(self) -> None:
            self.closed = True

    provider = ProviderIterator()
    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: provider,
    )
    db = app.state.session_factory()
    user = (
        db.query(User)
        .filter(User.email_normalized == "test-admin@example.com")
        .one()
    )
    response = stream_chat(
        ChatRequest(
            knowledge_base_id=knowledge_base_id,
            session_id=created_session["id"],
            question="中途断开",
            top_k=4,
        ),
        db,
        test_settings,
        app.state.rag_runtime,
        user,
        None,
    )

    async def consume_three_events_and_disconnect() -> None:
        iterator = response.body_iterator
        start = await anext(iterator)
        retrieval = await anext(iterator)
        delta = await anext(iterator)
        assert json.loads(start)["type"] == "start"
        assert json.loads(retrieval)["type"] == "retrieval"
        assert json.loads(delta)["type"] == "delta"
        await iterator.aclose()

    try:
        anyio.run(consume_three_events_and_disconnect)
    finally:
        db.close()

    assert provider.closed is True
    history = client.get(
        f"/api/sessions/{created_session['id']}/messages",
        params={"knowledge_base_id": knowledge_base_id},
    )
    messages = history.json()["data"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "第一段 [K1]"
    assert messages[1]["status"] == "cancelled"

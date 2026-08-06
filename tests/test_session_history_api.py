"""Session ownership, history persistence, and transaction API tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.exceptions import ModelServiceException
from app.repositories.session_repository import SessionRepository


def _create_knowledge_base(client: TestClient, name: str) -> str:
    response = client.post("/api/knowledge-bases", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _create_session(
    client: TestClient,
    knowledge_base_id: str,
    title: str = "新会话",
) -> dict:
    response = client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": title,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def _messages(
    client: TestClient,
    knowledge_base_id: str,
    session_id: str,
):
    return client.get(
        f"/api/sessions/{session_id}/messages",
        params={"knowledge_base_id": knowledge_base_id},
    )


def test_create_requires_existing_knowledge_base(client: TestClient) -> None:
    response = client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": str(uuid4()),
            "title": "不存在",
        },
    )

    assert response.status_code == 404
    assert response.json()["message"] == "知识库不存在"


def test_session_crud_filters_by_knowledge_base_and_deletes_messages(
    client: TestClient,
) -> None:
    first_kb_id = _create_knowledge_base(client, "session-kb-one")
    second_kb_id = _create_knowledge_base(client, "session-kb-two")
    first_session = _create_session(client, first_kb_id, "第一个会话")
    second_session = _create_session(client, second_kb_id, "第二个会话")

    first_list = client.get(
        "/api/sessions",
        params={"knowledge_base_id": first_kb_id},
    )
    assert first_list.status_code == 200
    assert [item["id"] for item in first_list.json()["data"]] == [
        first_session["id"]
    ]

    detail = client.get(
        f"/api/sessions/{first_session['id']}",
        params={"knowledge_base_id": first_kb_id},
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["knowledge_base_id"] == first_kb_id

    empty_history = _messages(client, first_kb_id, first_session["id"])
    assert empty_history.status_code == 200
    assert empty_history.json()["data"] == []

    for method, path in (
        (
            "GET",
            f"/api/sessions/{first_session['id']}",
        ),
        (
            "GET",
            f"/api/sessions/{first_session['id']}/messages",
        ),
        (
            "DELETE",
            f"/api/sessions/{first_session['id']}",
        ),
    ):
        cross_access = client.request(
            method,
            path,
            params={"knowledge_base_id": second_kb_id},
        )
        assert cross_access.status_code == 404
        assert "不属于" in cross_access.json()["message"]

    chat = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": first_kb_id,
            "session_id": first_session["id"],
            "question": "没有索引时会怎样？",
            "top_k": 4,
        },
    )
    assert chat.status_code == 409

    history = _messages(client, first_kb_id, first_session["id"])
    assert history.status_code == 200
    messages = history.json()["data"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "没有索引时会怎样？"
    assert messages[1]["status"] == "failed"
    assert all(item["session_id"] == first_session["id"] for item in messages)

    other_history = _messages(
        client,
        second_kb_id,
        second_session["id"],
    )
    assert other_history.status_code == 200
    assert other_history.json()["data"] == []

    deleted = client.delete(
        f"/api/sessions/{first_session['id']}",
        params={"knowledge_base_id": first_kb_id},
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["id"] == first_session["id"]
    assert _messages(
        client,
        first_kb_id,
        first_session["id"],
    ).status_code == 404

    surviving = client.get(
        f"/api/sessions/{second_session['id']}",
        params={"knowledge_base_id": second_kb_id},
    )
    assert surviving.status_code == 200

    repeated_delete = client.delete(
        f"/api/sessions/{first_session['id']}",
        params={"knowledge_base_id": first_kb_id},
    )
    assert repeated_delete.status_code == 404


def test_chat_rejects_session_owned_by_another_knowledge_base(
    client: TestClient,
) -> None:
    first_kb_id = _create_knowledge_base(client, "chat-owner-one")
    second_kb_id = _create_knowledge_base(client, "chat-owner-two")
    chat_session = _create_session(client, first_kb_id)

    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": second_kb_id,
            "session_id": chat_session["id"],
            "question": "跨库提问",
            "top_k": 4,
        },
    )

    assert response.status_code == 404
    assert "不属于" in response.json()["message"]
    assert _messages(
        client,
        first_kb_id,
        chat_session["id"],
    ).json()["data"] == []


def test_chat_without_session_creates_and_persists_one(
    client: TestClient,
) -> None:
    knowledge_base_id = _create_knowledge_base(client, "auto-session")
    question = "自动创建会话并保存历史"

    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": knowledge_base_id,
            "question": question,
            "top_k": 4,
        },
    )

    assert response.status_code == 409
    sessions = client.get(
        "/api/sessions",
        params={"knowledge_base_id": knowledge_base_id},
    ).json()["data"]
    assert len(sessions) == 1
    session_id = sessions[0]["id"]
    detail = client.get(
        f"/api/sessions/{session_id}",
        params={"knowledge_base_id": knowledge_base_id},
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["title"] == question
    assert len(_messages(
        client,
        knowledge_base_id,
        session_id,
    ).json()["data"]) == 2


def test_chat_activity_updates_default_title_and_session_order(
    client: TestClient,
) -> None:
    knowledge_base_id = _create_knowledge_base(client, "session-order")
    older = _create_session(client, knowledge_base_id, "新会话")
    newer = _create_session(client, knowledge_base_id, "保持标题")

    initial = client.get(
        "/api/sessions",
        params={"knowledge_base_id": knowledge_base_id},
    )
    assert [item["id"] for item in initial.json()["data"]] == [
        newer["id"],
        older["id"],
    ]

    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": older["id"],
            "question": "第一次问题会成为标题",
            "top_k": 4,
        },
    )
    assert response.status_code == 409

    updated = client.get(
        "/api/sessions",
        params={"knowledge_base_id": knowledge_base_id},
    )
    assert [item["id"] for item in updated.json()["data"]] == [
        older["id"],
        newer["id"],
    ]
    assert updated.json()["data"][0]["title"] == "第一次问题会成为标题"


def test_model_failure_persists_user_and_failed_assistant(
    client: TestClient,
    monkeypatch,
) -> None:
    knowledge_base_id = _create_knowledge_base(client, "model-failure")
    chat_session = _create_session(client, knowledge_base_id)

    def fail_generation(*_args, **_kwargs):
        raise ModelServiceException("模型失败", status_code=502)

    monkeypatch.setattr("app.api.chat.RagService.ask", fail_generation)
    monkeypatch.setattr(
        "app.api.chat.RagService.prepare_retrieval",
        lambda *_args, **_kwargs: None,
    )
    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": chat_session["id"],
            "question": "不会被保存",
            "top_k": 4,
        },
    )

    assert response.status_code == 502
    messages = _messages(
        client,
        knowledge_base_id,
        chat_session["id"],
    ).json()["data"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "不会被保存"
    assert messages[1]["status"] == "failed"
    assert messages[1]["error_code"] == "CHAT_REQUEST_FAILED"


def test_second_message_failure_rolls_back_user_message(
    client: TestClient,
    monkeypatch,
) -> None:
    knowledge_base_id = _create_knowledge_base(client, "history-rollback")
    chat_session = _create_session(client, knowledge_base_id)
    original = SessionRepository.save_message
    calls = 0

    def fail_second_message(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("assistant insert failed")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        SessionRepository,
        "save_message",
        fail_second_message,
    )
    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": chat_session["id"],
            "question": "事务回滚",
            "top_k": 4,
        },
    )

    assert response.status_code == 500
    assert _messages(
        client,
        knowledge_base_id,
        chat_session["id"],
    ).json()["data"] == []


def test_delete_failure_rolls_back_message_deletion(
    client: TestClient,
    monkeypatch,
) -> None:
    knowledge_base_id = _create_knowledge_base(client, "delete-rollback")
    chat_session = _create_session(client, knowledge_base_id)
    chat = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": chat_session["id"],
            "question": "删除也必须原子化",
            "top_k": 4,
        },
    )
    assert chat.status_code == 409

    def fail_session_delete(*_args, **_kwargs):
        raise RuntimeError("session delete failed")

    monkeypatch.setattr(
        SessionRepository,
        "delete_session",
        fail_session_delete,
    )
    deleted = client.delete(
        f"/api/sessions/{chat_session['id']}",
        params={"knowledge_base_id": knowledge_base_id},
    )

    assert deleted.status_code == 500
    detail = client.get(
        f"/api/sessions/{chat_session['id']}",
        params={"knowledge_base_id": knowledge_base_id},
    )
    assert detail.status_code == 200
    assert len(_messages(
        client,
        knowledge_base_id,
        chat_session["id"],
    ).json()["data"]) == 2

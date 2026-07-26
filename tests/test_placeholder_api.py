"""API contracts that remain outside the completed indexing tests."""

from uuid import uuid4

from fastapi.testclient import TestClient


def test_chat_uses_real_knowledge_base_lookup(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": str(uuid4()),
            "session_id": None,
            "question": "什么是 RAG？",
            "top_k": 4,
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == 404


def test_chat_rejects_question_over_4000_characters(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.api.chat.RetrievalService",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("route dependencies must not be constructed")
        ),
    )
    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": str(uuid4()),
            "question": "x" * 4001,
            "top_k": 4,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422


def test_file_management_routes_are_active(client: TestClient) -> None:
    knowledge_base_id = uuid4()
    file_id = uuid4()

    for method, path in (
        ("GET", f"/api/files?knowledge_base_id={knowledge_base_id}"),
        ("GET", f"/api/files/{file_id}"),
        ("DELETE", f"/api/files/{file_id}"),
    ):
        response = client.request(method, path)
        assert response.status_code == 404
        assert response.json()["code"] == 404


def test_session_routes_use_real_resource_validation(
    client: TestClient,
) -> None:
    knowledge_base_id = uuid4()
    session_id = uuid4()

    responses = (
        client.post(
            "/api/sessions",
            json={
                "knowledge_base_id": str(knowledge_base_id),
                "title": "测试会话",
            },
        ),
        client.get(
            "/api/sessions",
            params={"knowledge_base_id": str(knowledge_base_id)},
        ),
        client.get(
            f"/api/sessions/{session_id}",
            params={"knowledge_base_id": str(knowledge_base_id)},
        ),
        client.delete(
            f"/api/sessions/{session_id}",
            params={"knowledge_base_id": str(knowledge_base_id)},
        ),
    )

    for response in responses:
        assert response.status_code == 404
        assert response.json()["code"] == 404

"""Initialization-phase placeholder endpoint contracts."""

from uuid import uuid4

from fastapi.testclient import TestClient


def test_chat_returns_explicit_placeholder(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "knowledge_base_id": str(uuid4()),
            "session_id": None,
            "question": "什么是 RAG？",
            "top_k": 4,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "answer": "RAG 问答服务尚未完成初始化",
        "sources": [],
    }


def test_file_management_routes_return_501(client: TestClient) -> None:
    knowledge_base_id = uuid4()
    file_id = uuid4()

    for method, path in (
        ("GET", f"/api/files?knowledge_base_id={knowledge_base_id}"),
        ("GET", f"/api/files/{file_id}"),
        ("DELETE", f"/api/files/{file_id}"),
    ):
        response = client.request(method, path)
        assert response.status_code == 501
        assert response.json()["code"] == 501


def test_session_routes_return_501(client: TestClient) -> None:
    knowledge_base_id = uuid4()
    session_id = uuid4()
    requests = (
        (
            "POST",
            "/api/sessions",
            {"knowledge_base_id": str(knowledge_base_id), "title": "测试会话"},
        ),
        ("GET", f"/api/sessions?knowledge_base_id={knowledge_base_id}", None),
        ("GET", f"/api/sessions/{session_id}", None),
        ("DELETE", f"/api/sessions/{session_id}", None),
    )

    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 501
        assert response.json()["code"] == 501

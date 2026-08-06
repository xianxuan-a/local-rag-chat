"""Knowledge-base API integration tests."""

from uuid import UUID

from fastapi.testclient import TestClient


def create_knowledge_base(client: TestClient, name: str = "测试知识库") -> dict:
    response = client.post(
        "/api/knowledge-bases",
        json={"name": name, "description": "用于集成测试"},
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_create_list_get_and_delete_knowledge_base(client: TestClient) -> None:
    created = create_knowledge_base(client)
    UUID(created["id"])

    listed = client.get("/api/knowledge-bases")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [created["id"]]

    fetched = client.get(f"/api/knowledge-bases/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == "测试知识库"

    deleted = client.delete(f"/api/knowledge-bases/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["id"] == created["id"]

    missing = client.get(f"/api/knowledge-bases/{created['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == 404


def test_duplicate_name_returns_conflict(client: TestClient) -> None:
    create_knowledge_base(client, "不可重复")

    response = client.post(
        "/api/knowledge-bases",
        json={"name": "不可重复"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == 409


def test_update_persists_name_and_description(client: TestClient) -> None:
    first = create_knowledge_base(client, "可编辑知识库")
    create_knowledge_base(client, "冲突名称")

    updated = client.patch(
        f"/api/knowledge-bases/{first['id']}",
        json={"name": "编辑后名称", "description": ""},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "编辑后名称"
    assert updated.json()["data"]["description"] is None
    fetched = client.get(f"/api/knowledge-bases/{first['id']}")
    assert fetched.json()["data"]["name"] == "编辑后名称"

    conflict = client.patch(
        f"/api/knowledge-bases/{first['id']}",
        json={"name": "冲突名称"},
    )
    assert conflict.status_code == 409

    empty = client.patch(f"/api/knowledge-bases/{first['id']}", json={})
    assert empty.status_code == 422


def test_invalid_uuid_returns_uniform_422(client: TestClient) -> None:
    response = client.get("/api/knowledge-bases/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert "errors" in response.json()["data"]

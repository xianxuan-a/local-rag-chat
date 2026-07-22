"""Secure file-upload integration tests."""

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings


def create_kb(client: TestClient, name: str = "上传测试") -> str:
    response = client.post("/api/knowledge-bases", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_upload_persists_file_and_pending_record(
    client: TestClient, test_settings: Settings
) -> None:
    knowledge_base_id = create_kb(client)
    content = "本地知识库内容".encode()

    response = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("知识.txt", content, "text/plain")},
    )

    assert response.status_code == 201
    record = response.json()["data"]
    assert record["knowledge_base_id"] == knowledge_base_id
    assert record["original_name"] == "知识.txt"
    assert record["status"] == "PENDING"
    assert record["file_size"] == len(content)
    stored_path = test_settings.DATA_DIR / record["file_path"]
    assert stored_path.read_bytes() == content

    blocked_delete = client.delete(f"/api/knowledge-bases/{knowledge_base_id}")
    assert blocked_delete.status_code == 409


def test_upload_rejects_missing_knowledge_base(client: TestClient) -> None:
    response = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": str(uuid4())},
        files={"file": ("sample.txt", b"content", "text/plain")},
    )

    assert response.status_code == 404


def test_upload_rejects_invalid_extension(client: TestClient) -> None:
    knowledge_base_id = create_kb(client)

    response = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("program.exe", b"content", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_upload_rejects_path_traversal(client: TestClient) -> None:
    knowledge_base_id = create_kb(client)

    response = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("../escape.txt", b"content", "text/plain")},
    )

    assert response.status_code == 400


def test_upload_rejects_empty_and_oversized_files(
    client: TestClient, test_settings: Settings
) -> None:
    knowledge_base_id = create_kb(client)

    empty = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert empty.status_code == 400

    oversized = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={
            "file": (
                "large.txt",
                b"x" * (test_settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1),
                "text/plain",
            )
        },
    )
    assert oversized.status_code == 413
    assert list(test_settings.UPLOAD_DIR.glob("*.uploading")) == []

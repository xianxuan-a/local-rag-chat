"""Phase-one contract tests for CORS, UTC time and Real API summaries."""

from fastapi.testclient import TestClient


def test_cors_allows_vite_origin_and_rejects_unconfigured_origin(
    client: TestClient,
) -> None:
    allowed = client.options(
        "/api/knowledge-bases",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert allowed.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"]
        == "http://127.0.0.1:5173"
    )
    assert "access-control-allow-credentials" not in allowed.headers

    rejected = client.options(
        "/api/knowledge-bases",
        headers={
            "Origin": "https://unconfigured.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_knowledge_base_summary_and_time_have_real_server_semantics(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/knowledge-bases",
        json={"name": "阶段一契约", "description": ""},
    )
    assert created.status_code == 201
    item = created.json()["data"]
    assert item["file_count"] == 0
    assert item["chunk_count"] == 0
    assert item["status"] == "EMPTY"
    assert item["embedding_model"] == "text-embedding-v4"
    assert item["description"] is None
    assert item["created_at"].endswith(("Z", "+00:00"))
    assert item["updated_at"].endswith(("Z", "+00:00"))


def test_file_response_exposes_persisted_status_and_runtime_config(
    client: TestClient,
) -> None:
    knowledge_base = client.post(
        "/api/knowledge-bases",
        json={"name": "阶段一文件契约"},
    ).json()["data"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base["id"]},
        files={"file": ("contract.txt", b"real content", "text/plain")},
    )
    assert uploaded.status_code == 201
    item = uploaded.json()["data"]
    assert item["status"] == "PENDING"
    assert item["progress"] == 0
    assert item["chunk_count"] == 0
    assert item["has_active_vectors"] is False
    assert item["embedding_provider"] == "dashscope"
    assert item["embedding_model"] == "text-embedding-v4"
    assert item["embedding_dimension"] == 1024
    assert item["vector_metric"] == "cosine"
    assert item["created_at"].endswith(("Z", "+00:00"))

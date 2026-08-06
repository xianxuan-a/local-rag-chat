"""Application startup and health response tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from uuid import UUID


def test_health_returns_uniform_success(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {"status": "ok"},
    }


def test_live_and_ready_have_distinct_semantics(client: TestClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json()["data"] == {"status": "live"}
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"
    assert ready.json()["data"]["checks"] == {
        "sqlite": "ok",
        "data_dir": "ok",
        "upload_dir": "ok",
        "chroma_dir": "ok",
        "metadata_dir": "ok",
        "chroma": "ok",
        "job_worker": "ok",
    }


def test_request_id_is_validated_and_returned(client: TestClient) -> None:
    generated = client.get(
        "/health/live", headers={"X-Request-ID": "unsafe log text"}
    )
    UUID(generated.headers["X-Request-ID"])
    supplied = "11111111-1111-1111-1111-111111111111"
    echoed = client.get(
        "/health/live", headers={"X-Request-ID": supplied}
    )
    assert echoed.headers["X-Request-ID"] == supplied


def test_swagger_document_is_available(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_startup_creates_all_sqlite_tables(client: TestClient) -> None:
    table_names = set(inspect(client.app.state.engine).get_table_names())

    assert {
        "knowledge_bases",
        "file_records",
        "chat_sessions",
        "chat_messages",
    } <= table_names


def test_http_errors_keep_uniform_envelope(client: TestClient) -> None:
    response = client.get("/route-that-does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == 404
    assert response.json()["data"] is None


def test_unexpected_errors_hide_internal_details(app: FastAPI) -> None:
    @app.get("/_test/unexpected-error")
    def raise_unexpected_error() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/_test/unexpected-error")

    assert response.status_code == 500
    assert response.json() == {
        "code": 500,
        "message": "internal server error",
        "data": None,
    }
    assert "sensitive" not in response.text

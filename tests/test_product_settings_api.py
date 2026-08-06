"""Persistent, non-secret product-settings API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database.migrations import upgrade_database
from app.main import create_app
from app.models import ProductSettings
from tests.conftest import make_test_settings


def test_settings_read_update_and_secret_redaction(client, app) -> None:
    initial = client.get("/api/settings")
    assert initial.status_code == 200
    data = initial.json()["data"]
    assert data["source"] == "environment"
    assert "api_key" not in data
    assert set(data) >= {
        "chat_model",
        "retrieval_top_k",
        "retrieval_score_threshold",
        "rag_context_max_chars",
        "dashscope_api_key_configured",
    }

    updated = client.put(
        "/api/settings",
        json={
            "chat_model": "qwen3-max",
            "retrieval_top_k": 17,
            "retrieval_score_threshold": 0.41,
            "rag_context_max_chars": 24000,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["source"] == "persistent"
    assert updated.json()["data"]["retrieval_top_k"] == 17
    assert (
        app.state.rag_runtime.effective_settings().RETRIEVAL_TOP_K == 17
    )
    with app.state.session_factory() as db:
        record = db.get(ProductSettings, 1)
        assert record is not None
        assert record.chat_model == "qwen3-max"

    invalid = client.put(
        "/api/settings",
        json={
            "chat_model": None,
            "retrieval_top_k": 0,
            "retrieval_score_threshold": 2,
            "rag_context_max_chars": 20,
        },
    )
    assert invalid.status_code == 422


def test_settings_survive_application_restart(tmp_path) -> None:
    settings = make_test_settings(tmp_path, BOOTSTRAP_SECRET="restart-secret")
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    app = create_app(settings)
    with TestClient(app) as first:
        bootstrap = first.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "restart-secret"},
            json={
                "username": "restart-admin",
                "email": "restart@example.com",
                "password": "restart-password-123",
            },
        )
        assert bootstrap.status_code == 200
        login = first.post(
            "/api/auth/login",
            json={
                "identity": "restart-admin",
                "password": "restart-password-123",
            },
        )
        token = login.json()["data"]["access_token"]
        first.headers.update({"Authorization": f"Bearer {token}"})
        assert first.put(
            "/api/settings",
            json={
                "chat_model": "qwen3-max",
                "retrieval_top_k": 23,
                "retrieval_score_threshold": None,
                "rag_context_max_chars": 32000,
            },
        ).status_code == 200

    restarted = create_app(settings)
    with TestClient(restarted) as second:
        second.headers.update({"Authorization": f"Bearer {token}"})
        response = second.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["data"]["retrieval_top_k"] == 23
        assert response.json()["data"]["source"] == "persistent"

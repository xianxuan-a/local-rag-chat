"""Explicit local single-user authentication bypass."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database.migrations import upgrade_database
from app.main import create_app
from tests.conftest import make_test_settings


def test_local_single_user_mode_allows_real_api_without_token(tmp_path) -> None:
    settings = make_test_settings(tmp_path, AUTH_REQUIRED=False)
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/settings")
        update = client.put(
            "/api/settings",
            json={
                "chat_model": None,
                "retrieval_top_k": 7,
                "retrieval_score_threshold": None,
                "rag_context_max_chars": 12000,
            },
        )

    assert response.status_code == 200
    assert update.status_code == 200
    assert update.json()["data"]["retrieval_top_k"] == 7


def test_production_rejects_auth_bypass(tmp_path) -> None:
    with pytest.raises(
        ValueError, match="生产环境必须启用 AUTH_REQUIRED"
    ):
        make_test_settings(
            tmp_path,
            ENVIRONMENT="production",
            AUTH_REQUIRED=False,
            JWT_SECRET="production-jwt-secret",
            METRICS_SCRAPE_TOKEN="production-metrics-secret",
            BACKUP_SIGNING_KEY="production-backup-secret",
            BOOTSTRAP_SECRET="production-bootstrap-secret",
        )

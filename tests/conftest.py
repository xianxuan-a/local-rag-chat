"""Shared isolated application fixtures."""

from collections.abc import Iterator
from pathlib import Path
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.database.migrations import upgrade_database
from app.main import create_app


def wait_for_job(
    client: TestClient,
    submission,
    *,
    timeout_seconds: float = 5,
) -> dict:
    assert submission.status_code == 202, submission.text
    job_id = submission.json()["data"]["id"]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()["data"]
        if job["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"Job 未在 {timeout_seconds} 秒内终态：{job_id}")


def make_test_settings(root: Path, **overrides: object) -> Settings:
    data_dir = root / "data"
    values: dict[str, object] = {
        "LOG_DIR": root / "logs",
        "DATA_DIR": data_dir,
        "UPLOAD_DIR": data_dir / "uploads",
        "CHROMA_DIR": data_dir / "chroma",
        "METADATA_DIR": data_dir / "metadata",
        "CHAT_HISTORY_DIR": data_dir / "chat_history",
        "BACKUP_DIR": data_dir / "backups",
        "EVALUATION_DIR": data_dir / "evaluations",
        "DATABASE_URL": f"sqlite:///{(data_dir / 'metadata' / 'test.db').as_posix()}",
        "MAX_UPLOAD_SIZE_MB": 1,
        "JWT_SECRET": "test-jwt-secret-that-is-long-and-explicit",
        "AUTH_REQUIRED": True,
        "METRICS_SCRAPE_TOKEN": "test-metrics-token",
        "BACKUP_SIGNING_KEY": "test-backup-signing-key",
        "BOOTSTRAP_SECRET": "test-bootstrap-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return make_test_settings(tmp_path)


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    test_settings.ensure_directories()
    upgrade_database(test_settings.DATABASE_URL)
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        bootstrap = test_client.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "test-bootstrap-secret"},
            json={
                "username": "test-admin",
                "email": "test-admin@example.com",
                "password": "test-password-123",
            },
        )
        assert bootstrap.status_code == 200, bootstrap.text
        login = test_client.post(
            "/api/auth/login",
            json={
                "identity": "TEST-ADMIN@example.com",
                "password": "test-password-123",
            },
        )
        assert login.status_code == 200, login.text
        token = login.json()["data"]["access_token"]
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        yield test_client

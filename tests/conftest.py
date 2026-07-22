"""Shared isolated application fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_test_settings(root: Path, **overrides: object) -> Settings:
    data_dir = root / "data"
    values: dict[str, object] = {
        "LOG_DIR": root / "logs",
        "DATA_DIR": data_dir,
        "UPLOAD_DIR": data_dir / "uploads",
        "CHROMA_DIR": data_dir / "chroma",
        "METADATA_DIR": data_dir / "metadata",
        "CHAT_HISTORY_DIR": data_dir / "chat_history",
        "DATABASE_URL": f"sqlite:///{(data_dir / 'metadata' / 'test.db').as_posix()}",
        "MAX_UPLOAD_SIZE_MB": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return make_test_settings(tmp_path)


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

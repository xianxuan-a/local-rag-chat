"""Configuration path and directory initialization tests."""

from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT, Settings, get_settings
from tests.conftest import make_test_settings


def test_default_project_root_is_repository_root() -> None:
    get_settings.cache_clear()
    settings = get_settings()

    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert settings.DATA_DIR == PROJECT_ROOT / "data"
    assert settings.UPLOAD_DIR == PROJECT_ROOT / "data" / "uploads"


def test_configured_directories_can_be_created(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)

    directories = settings.ensure_directories()

    assert directories
    assert all(path.is_dir() for path in directories)
    assert settings.DATABASE_URL.endswith("/data/metadata/test.db")


def test_default_settings_values_are_valid() -> None:
    settings = Settings(_env_file=None, DASHSCOPE_API_KEY="")

    assert settings.HOST == "127.0.0.1"
    assert settings.CHUNK_SIZE == 1000
    assert settings.CHUNK_OVERLAP == 200
    assert settings.RETRIEVAL_TOP_K == 5
    assert settings.RETRIEVAL_SCORE_THRESHOLD is None
    assert settings.CHAT_MODEL is None
    assert settings.CHAT_TEMPERATURE == 0.1
    assert settings.CHAT_MAX_TOKENS == 1024
    assert settings.CHAT_TIMEOUT_SECONDS == 60
    assert settings.CHAT_MAX_ATTEMPTS == 2
    assert settings.RAG_CONTEXT_MAX_CHARS == 12000
    assert settings.missing_chat_configuration() == (
        "CHAT_MODEL",
        "DASHSCOPE_API_KEY",
    )
    assert settings.EMBEDDING_PROTOCOL_VERSION == "dashscope-text-embedding-v1"
    assert settings.VECTOR_DISTANCE_METRIC == "cosine"
    assert settings.ALLOWED_FILE_EXTENSIONS == [".txt", ".pdf", ".csv", ".json"]


def test_legacy_chat_model_sentinel_is_treated_as_unconfigured() -> None:
    settings = Settings(
        _env_file=None,
        CHAT_MODEL="not-configured",
        DASHSCOPE_API_KEY="test-key",
    )

    assert settings.CHAT_MODEL is None
    assert settings.missing_chat_configuration() == ("CHAT_MODEL",)


def _production_secrets() -> dict[str, str]:
    return {
        "JWT_SECRET": "j" * 32,
        "METRICS_SCRAPE_TOKEN": "m" * 32,
        "BACKUP_SIGNING_KEY": "b" * 32,
        "BOOTSTRAP_SECRET": "s" * 32,
    }


def test_production_auth_with_strong_secrets_is_valid() -> None:
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        AUTH_REQUIRED=True,
        **_production_secrets(),
    )

    assert settings.ENVIRONMENT == "production"
    assert settings.AUTH_REQUIRED is True


def test_production_missing_secret_fails_without_leaking_values() -> None:
    secrets = _production_secrets()
    exposed_value = secrets["JWT_SECRET"]
    secrets["BOOTSTRAP_SECRET"] = ""

    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            AUTH_REQUIRED=True,
            **secrets,
        )

    message = str(error.value)
    assert "BOOTSTRAP_SECRET" in message
    assert exposed_value not in message


def test_production_weak_secret_fails_without_leaking_values() -> None:
    secrets = _production_secrets()
    weak_value = "weak-secret"
    secrets["JWT_SECRET"] = weak_value

    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            AUTH_REQUIRED=True,
            **secrets,
        )

    message = str(error.value)
    assert "JWT_SECRET" in message
    assert "至少 32 UTF-8 bytes" in message
    assert weak_value not in message

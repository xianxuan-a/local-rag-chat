"""Configuration path and directory initialization tests."""

from pathlib import Path

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
    settings = Settings(_env_file=None)

    assert settings.CHUNK_SIZE == 1000
    assert settings.CHUNK_OVERLAP == 200
    assert settings.RETRIEVAL_TOP_K == 4
    assert settings.ALLOWED_FILE_EXTENSIONS == [".txt", ".pdf", ".csv", ".json"]

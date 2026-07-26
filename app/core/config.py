"""Application configuration backed by Pydantic Settings.

Only inexpensive configuration parsing happens at import time.  Directory
creation is deliberately exposed as an explicit startup operation so importing
the application never mutates the filesystem.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = _PROJECT_ROOT


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and ``.env``."""

    PROJECT_ROOT: ClassVar[Path] = _PROJECT_ROOT

    APP_NAME: str = "Local RAG Chat"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8000, ge=1, le=65535)

    LOG_LEVEL: str = "INFO"
    LOG_DIR: Path = _PROJECT_ROOT / "logs"

    DATA_DIR: Path = _PROJECT_ROOT / "data"
    UPLOAD_DIR: Path = _PROJECT_ROOT / "data" / "uploads"
    CHROMA_DIR: Path = _PROJECT_ROOT / "data" / "chroma"
    METADATA_DIR: Path = _PROJECT_ROOT / "data" / "metadata"
    CHAT_HISTORY_DIR: Path = _PROJECT_ROOT / "data" / "chat_history"
    DATABASE_URL: str = (
        f"sqlite:///{(_PROJECT_ROOT / 'data' / 'metadata' / 'local_rag_chat.db').as_posix()}"
    )

    EMBEDDING_PROVIDER: str = "dashscope"
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIMENSION: int = Field(default=1024, ge=1)
    EMBEDDING_NORMALIZATION: str = "l2"
    EMBEDDING_PROTOCOL_VERSION: str = "dashscope-text-embedding-v1"
    VECTOR_DISTANCE_METRIC: str = "cosine"
    DASHSCOPE_API_KEY: SecretStr = SecretStr("")
    DASHSCOPE_BASE_URL: str | None = None
    EMBEDDING_REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    EMBEDDING_MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    EMBEDDING_BATCH_SIZE: int = Field(default=10, ge=1, le=10)
    CHAT_MODEL: str | None = None
    CHAT_TEMPERATURE: float = Field(default=0.1, ge=0, lt=2)
    CHAT_MAX_TOKENS: int = Field(default=1024, ge=1)
    CHAT_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)
    CHAT_MAX_ATTEMPTS: int = Field(default=2, ge=1, le=2)
    RAG_CONTEXT_MAX_CHARS: int = Field(default=12000, ge=1)
    CHUNK_SIZE: int = Field(default=1000, ge=1)
    CHUNK_OVERLAP: int = Field(default=200, ge=0)
    RETRIEVAL_TOP_K: int = Field(default=5, ge=1, le=100)
    RETRIEVAL_SCORE_THRESHOLD: float | None = Field(
        default=None, ge=-1.0, le=1.0
    )
    REBUILD_HTTP_TIMEOUT_SECONDS: float = Field(default=3600.0, gt=0)
    MAX_UPLOAD_SIZE_MB: int = Field(default=20, ge=1)
    ALLOWED_FILE_EXTENSIONS: list[str] = Field(
        default_factory=lambda: [".txt", ".pdf", ".csv", ".json"]
    )

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator(
        "LOG_DIR",
        "DATA_DIR",
        "UPLOAD_DIR",
        "CHROMA_DIR",
        "METADATA_DIR",
        "CHAT_HISTORY_DIR",
        mode="before",
    )
    @classmethod
    def resolve_project_path(cls, value: str | Path) -> Path:
        """Resolve relative configured paths against the project root."""

        path = Path(value).expanduser()
        if not path.is_absolute():
            path = cls.PROJECT_ROOT / path
        return path.resolve()

    @field_validator("ALLOWED_FILE_EXTENSIONS")
    @classmethod
    def normalize_extensions(cls, values: list[str]) -> list[str]:
        """Normalize extensions to unique, lowercase values with a leading dot."""

        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip().lower()
            if not value:
                raise ValueError("ALLOWED_FILE_EXTENSIONS 不能包含空值")
            extension = value if value.startswith(".") else f".{value}"
            if any(separator in extension for separator in ("/", "\\")):
                raise ValueError("文件扩展名不能包含路径分隔符")
            if extension not in normalized:
                normalized.append(extension)
        if not normalized:
            raise ValueError("ALLOWED_FILE_EXTENSIONS 不能为空")
        return normalized

    @field_validator("LOG_LEVEL")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed_levels:
            raise ValueError(f"不支持的日志等级: {value}")
        return level

    @field_validator(
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_NORMALIZATION",
        "EMBEDDING_PROTOCOL_VERSION",
        "VECTOR_DISTANCE_METRIC",
    )
    @classmethod
    def normalize_embedding_text_setting(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Embedding 配置项不能为空")
        return normalized

    @field_validator("DASHSCOPE_BASE_URL", mode="before")
    @classmethod
    def normalize_dashscope_base_url(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        from urllib.parse import urlsplit

        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("DASHSCOPE_BASE_URL 必须是合法的 HTTP 或 HTTPS 地址")
        return normalized.rstrip("/")

    @field_validator("CHAT_MODEL", mode="before")
    @classmethod
    def normalize_chat_model(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized or normalized.lower() == "not-configured":
            return None
        return normalized

    @field_validator("RETRIEVAL_SCORE_THRESHOLD", mode="before")
    @classmethod
    def empty_retrieval_threshold_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("API_PREFIX")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        prefix = value.strip()
        if not prefix:
            raise ValueError("API_PREFIX 不能为空")
        prefix = prefix if prefix.startswith("/") else f"/{prefix}"
        return prefix.rstrip("/") or "/"

    @field_validator("DATABASE_URL")
    @classmethod
    def resolve_sqlite_database_url(cls, value: str) -> str:
        """Anchor relative SQLite files to the project instead of the process CWD."""

        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        database_path = value[len(prefix) :]
        if not database_path or database_path == ":memory:":
            return value
        path = Path(database_path).expanduser()
        if not path.is_absolute():
            path = (cls.PROJECT_ROOT / path).resolve()
        return f"{prefix}{path.as_posix()}"

    @model_validator(mode="after")
    def validate_chunk_window(self) -> "Settings":
        if self.CHUNK_OVERLAP >= self.CHUNK_SIZE:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        return self

    def ensure_directories(self) -> tuple[Path, ...]:
        """Create all runtime directories idempotently and return their paths."""

        directories = (
            self.LOG_DIR,
            self.DATA_DIR,
            self.UPLOAD_DIR,
            self.CHROMA_DIR,
            self.METADATA_DIR,
            self.CHAT_HISTORY_DIR,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        return directories

    def missing_chat_configuration(self) -> tuple[str, ...]:
        """Return missing chat setting names without contacting a provider."""

        missing: list[str] = []
        if not self.CHAT_MODEL:
            missing.append("CHAT_MODEL")
        if not self.DASHSCOPE_API_KEY.get_secret_value():
            missing.append("DASHSCOPE_API_KEY")
        return tuple(missing)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()


def initialize_directories(app_settings: Settings | None = None) -> tuple[Path, ...]:
    """Initialize configured runtime directories during application startup."""

    return (app_settings or get_settings()).ensure_directories()


settings = get_settings()

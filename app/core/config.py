"""Application configuration backed by Pydantic Settings.

Only inexpensive configuration parsing happens at import time.  Directory
creation is deliberately exposed as an explicit startup operation so importing
the application never mutates the filesystem.
"""

from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import ClassVar

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.retrieval_modes import DEFAULT_FRESHNESS_TERMS, RetrievalMode


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = _PROJECT_ROOT


def normalize_listen_host(value: object) -> str:
    """Normalize a Uvicorn host without resolving DNS names."""

    if value is None:
        raise ValueError("HOST 不能为空")
    host = str(value).strip()
    if not host:
        raise ValueError("HOST 不能为空")
    if "%" in host:
        raise ValueError("HOST 不支持 IPv6 zone identifier")
    if host.startswith("[") or host.endswith("]"):
        if not (host.startswith("[") and host.endswith("]")):
            raise ValueError("HOST 的 IPv6 方括号不完整")
        candidate = host[1:-1]
        try:
            address = ip_address(candidate)
        except ValueError as exc:
            raise ValueError("HOST 方括号内必须是 IPv6 地址") from exc
        if address.version != 6:
            raise ValueError("HOST 只允许为 IPv6 地址使用方括号")
        return str(address)
    if "[" in host or "]" in host:
        raise ValueError("HOST 的 IPv6 方括号格式无效")
    try:
        return str(ip_address(host))
    except ValueError:
        return host.casefold() if host.casefold() == "localhost" else host


def is_explicit_loopback_host(host: str) -> bool:
    """Return true only for literal loopback values; never perform DNS."""

    if host.casefold() == "localhost":
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    if address.version == 4:
        return address.is_loopback
    return address == ip_address("::1")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and ``.env``."""

    PROJECT_ROOT: ClassVar[Path] = _PROJECT_ROOT

    APP_NAME: str = "Local RAG Chat"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    HOST: str = "127.0.0.1"
    PORT: int = Field(default=8000, ge=1, le=65535)
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )

    LOG_LEVEL: str = "INFO"
    LOG_DIR: Path = _PROJECT_ROOT / "logs"
    LOG_MAX_BYTES: int = Field(default=10 * 1024 * 1024, ge=1024)
    LOG_BACKUP_COUNT: int = Field(default=5, ge=1, le=100)

    DATA_DIR: Path = _PROJECT_ROOT / "data"
    UPLOAD_DIR: Path = _PROJECT_ROOT / "data" / "uploads"
    CHROMA_DIR: Path = _PROJECT_ROOT / "data" / "chroma"
    METADATA_DIR: Path = _PROJECT_ROOT / "data" / "metadata"
    CHAT_HISTORY_DIR: Path = _PROJECT_ROOT / "data" / "chat_history"
    BACKUP_DIR: Path = _PROJECT_ROOT / "data" / "backups"
    EVALUATION_DIR: Path = _PROJECT_ROOT / "data" / "evaluations"
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
    WEB_SEARCH_ENABLED: bool = False
    DEFAULT_RETRIEVAL_MODE: RetrievalMode = RetrievalMode.KNOWLEDGE_FIRST
    RETRIEVAL_MIN_EVIDENCE_COUNT: int = Field(default=1, ge=1, le=100)
    RETRIEVAL_FRESHNESS_TERMS: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FRESHNESS_TERMS)
    )
    WEB_SEARCH_PROVIDER: str = "disabled"
    WEB_SEARCH_API_KEY: SecretStr = SecretStr("")
    WEB_SEARCH_ALLOWED_ROLES: list[str] = Field(
        default_factory=lambda: ["ADMIN", "USER"]
    )
    WEB_SEARCH_ALLOWED_DOMAINS: list[str] = Field(default_factory=list)
    WEB_SEARCH_BLOCKED_DOMAINS: list[str] = Field(default_factory=list)
    WEB_SEARCH_RESULT_LIMIT: int = Field(default=5, ge=1, le=20)
    WEB_FETCH_MAX_PAGES: int = Field(default=5, ge=1, le=20)
    WEB_FETCH_MAX_PAGES_PER_DOMAIN: int = Field(default=2, ge=1, le=10)
    WEB_SEARCH_QUERY_MAX_CHARS: int = Field(default=512, ge=32, le=4000)
    WEB_PAGE_MAX_CHARS: int = Field(default=6000, ge=500, le=100_000)
    WEB_FETCH_MAX_RESPONSE_BYTES: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
    )
    WEB_SEARCH_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0, le=60)
    WEB_FETCH_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0, le=60)
    WEB_TOTAL_TIMEOUT_SECONDS: float = Field(default=12.0, gt=0, le=120)
    WEB_FETCH_MAX_REDIRECTS: int = Field(default=3, ge=0, le=10)
    WEB_SEARCH_CACHE_TTL_SECONDS: int = Field(default=300, ge=0, le=3600)
    WEB_QUERY_LOG_MODE: str = "digest"
    WEB_CONTENT_CACHE_ENABLED: bool = False
    REBUILD_HTTP_TIMEOUT_SECONDS: float = Field(default=3600.0, gt=0)
    MAX_UPLOAD_SIZE_MB: int = Field(default=20, ge=1)
    ALLOWED_FILE_EXTENSIONS: list[str] = Field(
        default_factory=lambda: [".txt", ".pdf", ".csv", ".json"]
    )

    JWT_SECRET: SecretStr = SecretStr("")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)
    AUTH_REQUIRED: bool = False
    ALLOW_REGISTRATION: bool = True
    METRICS_SCRAPE_TOKEN: SecretStr = SecretStr("")
    BACKUP_SIGNING_KEY: SecretStr = SecretStr("")
    BOOTSTRAP_SECRET: SecretStr = SecretStr("")

    JOB_POLL_INTERVAL_SECONDS: float = Field(default=0.25, gt=0, le=10)
    JOB_LEASE_SECONDS: int = Field(default=30, ge=5, le=3600)
    JOB_HEARTBEAT_SECONDS: int = Field(default=5, ge=1, le=300)
    JOB_PROGRESS_MIN_INTERVAL_SECONDS: float = Field(default=1.0, ge=1.0)
    BACKUP_MAX_MEMBERS: int = Field(default=10000, ge=1)
    BACKUP_MAX_MEMBER_BYTES: int = Field(default=512 * 1024 * 1024, ge=1)
    BACKUP_MAX_TOTAL_BYTES: int = Field(default=4 * 1024 * 1024 * 1024, ge=1)
    BACKUP_MAX_COMPRESSION_RATIO: float = Field(default=200.0, ge=1)

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("HOST", mode="before")
    @classmethod
    def normalize_host(cls, value: object) -> str:
        return normalize_listen_host(value)

    @field_validator(
        "LOG_DIR",
        "DATA_DIR",
        "UPLOAD_DIR",
        "CHROMA_DIR",
        "METADATA_DIR",
        "CHAT_HISTORY_DIR",
        "BACKUP_DIR",
        "EVALUATION_DIR",
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

    @field_validator("WEB_SEARCH_PROVIDER")
    @classmethod
    def normalize_web_search_provider(cls, value: str) -> str:
        normalized = value.strip().casefold()
        return normalized or "disabled"

    @field_validator("WEB_QUERY_LOG_MODE")
    @classmethod
    def validate_web_query_log_mode(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized != "digest":
            raise ValueError("WEB_QUERY_LOG_MODE 仅支持 digest")
        return "digest"

    @field_validator("WEB_SEARCH_ALLOWED_ROLES")
    @classmethod
    def normalize_web_search_allowed_roles(
        cls, values: list[str]
    ) -> list[str]:
        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip().upper()
            if value not in {"ADMIN", "USER"}:
                raise ValueError(
                    f"WEB_SEARCH_ALLOWED_ROLES 包含未知角色：{raw_value}"
                )
            if value not in normalized:
                normalized.append(value)
        return normalized

    @field_validator(
        "WEB_SEARCH_ALLOWED_DOMAINS",
        "WEB_SEARCH_BLOCKED_DOMAINS",
    )
    @classmethod
    def normalize_web_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip().strip(".").casefold()
            if not value:
                raise ValueError("联网域名列表不能包含空值")
            try:
                value = value.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise ValueError(f"联网域名无效：{raw_value}") from exc
            if any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789.-"
                for character in value
            ):
                raise ValueError(f"联网域名无效：{raw_value}")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @field_validator("RETRIEVAL_FRESHNESS_TERMS")
    @classmethod
    def normalize_freshness_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip()
            if not value or len(value) > 64:
                raise ValueError("时效词必须为 1 到 64 个字符")
            folded = value.casefold()
            if folded not in {item.casefold() for item in normalized}:
                normalized.append(value)
        if not normalized or len(normalized) > 64:
            raise ValueError("时效词数量必须为 1 到 64")
        return normalized

    @field_validator("API_PREFIX")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        prefix = value.strip()
        if not prefix:
            raise ValueError("API_PREFIX 不能为空")
        prefix = prefix if prefix.startswith("/") else f"/{prefix}"
        return prefix.rstrip("/") or "/"

    @field_validator("CORS_ALLOWED_ORIGINS")
    @classmethod
    def normalize_cors_origins(cls, values: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip().rstrip("/")
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"CORS origin 不是合法的 HTTP Origin：{raw_value}")
            if value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("CORS_ALLOWED_ORIGINS 不能为空")
        return normalized

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
        if self.JOB_HEARTBEAT_SECONDS >= self.JOB_LEASE_SECONDS:
            raise ValueError("JOB_HEARTBEAT_SECONDS 必须小于 JOB_LEASE_SECONDS")
        overlap = set(self.WEB_SEARCH_ALLOWED_DOMAINS) & set(
            self.WEB_SEARCH_BLOCKED_DOMAINS
        )
        if overlap:
            raise ValueError(
                "联网允许域名与禁止域名重复：" + ", ".join(sorted(overlap))
            )
        if self.WEB_TOTAL_TIMEOUT_SECONDS < min(
            self.WEB_SEARCH_TIMEOUT_SECONDS,
            self.WEB_FETCH_TIMEOUT_SECONDS,
        ):
            raise ValueError(
                "WEB_TOTAL_TIMEOUT_SECONDS 不能小于搜索或抓取超时"
            )
        if self.WEB_CONTENT_CACHE_ENABLED:
            raise ValueError(
                "本版本不持久化网页正文，WEB_CONTENT_CACHE_ENABLED 必须为 false"
            )
        environment = self.ENVIRONMENT.strip().casefold()
        if environment == "production" and not self.AUTH_REQUIRED:
            raise ValueError("生产环境必须启用 AUTH_REQUIRED")
        if not self.AUTH_REQUIRED and not is_explicit_loopback_host(self.HOST):
            raise ValueError(
                "AUTH_REQUIRED=false 仅允许明确的 loopback HOST；"
                f"当前 HOST={self.HOST!r}。局域网、容器或反向代理监听必须启用认证"
            )
        if environment == "production":
            secret_names = (
                "JWT_SECRET",
                "METRICS_SCRAPE_TOKEN",
                "BACKUP_SIGNING_KEY",
                "BOOTSTRAP_SECRET",
            )
            secret_values = {
                name: getattr(self, name).get_secret_value()
                for name in secret_names
            }
            missing = [
                name for name, value in secret_values.items() if not value
            ]
            if missing:
                raise ValueError(
                    "生产环境缺少显式 Secret：" + ", ".join(missing)
                )
            weak = [
                name
                for name, value in secret_values.items()
                if len(value.encode("utf-8")) < 32
            ]
            if weak:
                raise ValueError(
                    "生产环境 Secret 强度不足（至少 32 UTF-8 bytes）："
                    + ", ".join(weak)
                )
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
            self.BACKUP_DIR,
            self.EVALUATION_DIR,
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

    def web_search_provider_configured(self) -> bool:
        """Report only configurations backed by an installed provider."""

        return (
            self.WEB_SEARCH_PROVIDER not in {"", "disabled", "none"}
            and bool(self.WEB_SEARCH_API_KEY.get_secret_value())
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()


def initialize_directories(app_settings: Settings | None = None) -> tuple[Path, ...]:
    """Initialize configured runtime directories during application startup."""

    return (app_settings or get_settings()).ensure_directories()


settings = get_settings()

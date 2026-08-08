"""Configuration path and directory initialization tests."""

import logging
from itertools import combinations
from pathlib import Path

import pytest

from app.core.config import (
    PRODUCTION_SECRET_POLICIES,
    PROJECT_ROOT,
    Settings,
    get_settings,
    production_secret_problem,
)
from scripts.init_secrets import SECRET_NAMES, initialize_secrets
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
    assert settings.AUTH_RATE_LIMIT_ENABLED is True
    assert settings.TRUSTED_PROXY_CIDRS == []
    assert settings.TRUSTED_PROXY_HOSTS == []


def test_trusted_proxy_configuration_is_canonical_and_validated() -> None:
    settings = Settings(
        _env_file=None,
        TRUSTED_PROXY_CIDRS=["10.1.2.3/24", "2001:db8::1/64"],
        TRUSTED_PROXY_HOSTS=["Frontend", "edge-proxy.internal"],
    )

    assert settings.TRUSTED_PROXY_CIDRS == ["10.1.2.0/24", "2001:db8::/64"]
    assert settings.TRUSTED_PROXY_HOSTS == ["frontend", "edge-proxy.internal"]
    with pytest.raises(ValueError):
        Settings(_env_file=None, TRUSTED_PROXY_CIDRS=["not-a-network"])
    with pytest.raises(ValueError):
        Settings(_env_file=None, TRUSTED_PROXY_HOSTS=["https://proxy:443"])


def test_rate_limit_ttl_and_backoff_boundaries_are_validated() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            AUTH_RATE_LIMIT_TTL_SECONDS=60,
            REGISTER_RATE_LIMIT_WINDOW_SECONDS=61,
        )
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            LOGIN_RATE_LIMIT_BACKOFF_BASE_SECONDS=10,
            LOGIN_RATE_LIMIT_BACKOFF_MAX_SECONDS=9,
        )


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
        "JWT_SECRET": "ls53Qz9CWbEu3_tMb-97GzqFmdTDqf66",
        "METRICS_SCRAPE_TOKEN": "BFKdWvFvLNN7MAMtStzgJWbEt452RurY",
        "BACKUP_SIGNING_KEY": "RfcJuDc5Mlmttw7XXSC-wqeA5lU4ae_-",
        "BOOTSTRAP_SECRET": "irOgAilJbdwl72bF2PXKXSaRUOtVmzJf",
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


def test_production_cannot_disable_authentication_rate_limits() -> None:
    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            AUTH_REQUIRED=True,
            AUTH_RATE_LIMIT_ENABLED=False,
            **_production_secrets(),
        )

    assert "AUTH_RATE_LIMIT_ENABLED" in str(error.value)


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
    assert "少于 32 UTF-8 bytes" in message
    assert weak_value not in message


@pytest.mark.parametrize(
    "bad_value",
    (
        "",
        " " * 32,
        "x",
        "0123456789abcdefghijklmnopqrstu",
        "x" * 64,
        "abc" * 21,
        "abcd" * 16,
        "change-me-" * 8,
        "replace-me-" * 8,
        "example-value-" * 4,
    ),
)
def test_production_secret_policy_rejects_boundary_and_obvious_weak_values(
    bad_value: str,
) -> None:
    values = _production_secrets()
    values["JWT_SECRET"] = bad_value

    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            AUTH_REQUIRED=True,
            **values,
        )

    message = str(error.value)
    assert "JWT_SECRET" in message
    if bad_value.strip():
        assert bad_value not in message


@pytest.mark.parametrize(
    ("left", "right"), tuple(combinations(PRODUCTION_SECRET_POLICIES, 2))
)
def test_production_secrets_cannot_be_reused_across_purposes(
    left: str,
    right: str,
) -> None:
    values = _production_secrets()
    reused_value = values[left]
    values[right] = reused_value

    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            AUTH_REQUIRED=True,
            **values,
        )

    message = str(error.value)
    assert left in message
    assert right in message
    assert reused_value not in message


def test_development_keeps_explicitly_scoped_weak_secret_policy() -> None:
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        AUTH_REQUIRED=False,
        JWT_SECRET="dev",
        METRICS_SCRAPE_TOKEN="dev",
        BACKUP_SIGNING_KEY="dev",
        BOOTSTRAP_SECRET="dev",
    )

    assert settings.ENVIRONMENT == "development"


def test_production_secret_policy_accepts_exact_length_boundary() -> None:
    boundary_value = _production_secrets()["JWT_SECRET"]

    assert len(boundary_value.encode("utf-8")) == 32
    assert production_secret_problem("JWT_SECRET", boundary_value) is None


def test_secret_values_are_redacted_from_repr_dump_and_logs(caplog) -> None:
    values = _production_secrets()
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        AUTH_REQUIRED=True,
        **values,
    )

    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("settings=%r", settings)
        logging.getLogger(__name__).info("dump=%r", settings.model_dump())

    rendered = "\n".join(
        (repr(settings), str(settings.model_dump()), settings.model_dump_json(), caplog.text)
    )
    for value in values.values():
        assert value not in rendered
    assert "**********" in rendered


def test_init_secrets_generates_distinct_policy_compliant_values(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / ".env"
    preserved = _production_secrets()["JWT_SECRET"]
    env_file.write_text(
        f"JWT_SECRET={preserved}\nMETRICS_SCRAPE_TOKEN=\n",
        encoding="utf-8",
    )

    generated_names = initialize_secrets(env_file)
    output = capsys.readouterr().out
    parsed = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    generated_values = [parsed[name] for name in SECRET_NAMES]

    assert generated_names == (
        "METRICS_SCRAPE_TOKEN",
        "BACKUP_SIGNING_KEY",
        "BOOTSTRAP_SECRET",
    )
    assert parsed["JWT_SECRET"] == preserved
    assert len(set(generated_values)) == len(SECRET_NAMES)
    assert all(
        production_secret_problem(name, parsed[name]) is None
        for name in SECRET_NAMES
    )
    assert all(value not in output for value in generated_values)

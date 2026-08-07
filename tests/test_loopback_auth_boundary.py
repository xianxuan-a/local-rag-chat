"""Network binding boundary for the local authentication bypass."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from app.core.config import Settings, is_explicit_loopback_host


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("configured_host", "normalized_host"),
    (
        ("127.0.0.1", "127.0.0.1"),
        ("127.12.34.56", "127.12.34.56"),
        ("localhost", "localhost"),
        ("LOCALHOST", "localhost"),
        ("::1", "::1"),
        ("[::1]", "::1"),
    ),
)
def test_auth_bypass_accepts_only_explicit_loopback_hosts(
    configured_host: str,
    normalized_host: str,
) -> None:
    settings = Settings(
        _env_file=None,
        HOST=configured_host,
        AUTH_REQUIRED=False,
    )

    assert settings.HOST == normalized_host
    assert is_explicit_loopback_host(settings.HOST)


@pytest.mark.parametrize(
    "host",
    (
        "0.0.0.0",
        "::",
        "[::]",
        "192.168.1.25",
        "10.0.0.8",
        "8.8.8.8",
        "backend",
        "localhost.",
        "::ffff:127.0.0.1",
    ),
)
def test_auth_bypass_rejects_non_loopback_or_unproven_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="AUTH_REQUIRED=false.*loopback HOST"):
        Settings(_env_file=None, HOST=host, AUTH_REQUIRED=False)


def test_authenticated_development_allows_non_loopback_binding() -> None:
    settings = Settings(
        _env_file=None,
        HOST="0.0.0.0",
        AUTH_REQUIRED=True,
    )

    assert settings.HOST == "0.0.0.0"
    assert settings.AUTH_REQUIRED is True


def test_default_development_configuration_is_loopback_only() -> None:
    settings = Settings(_env_file=None)

    assert settings.ENVIRONMENT == "development"
    assert settings.AUTH_REQUIRED is False
    assert settings.HOST == "127.0.0.1"


def test_production_still_rejects_auth_bypass_on_loopback() -> None:
    with pytest.raises(ValueError, match="生产环境必须启用 AUTH_REQUIRED"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            HOST="127.0.0.1",
            AUTH_REQUIRED=False,
        )


@pytest.mark.parametrize(
    "host", (None, "", "[::1", "::1]", "[127.0.0.1]", "::1%1")
)
def test_invalid_host_syntax_is_rejected_even_with_authentication(
    host: object,
) -> None:
    with pytest.raises(ValueError, match="HOST"):
        Settings(_env_file=None, HOST=host, AUTH_REQUIRED=True)


def test_unsafe_run_py_configuration_exits_before_socket_bind() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    environment = os.environ.copy()
    environment.update(
        {
            "ENVIRONMENT": "development",
            "AUTH_REQUIRED": "false",
            "HOST": "0.0.0.0",
            "PORT": str(port),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    result = subprocess.run(
        [sys.executable, "run.py"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "AUTH_REQUIRED=false" in output
    assert "HOST" in output
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))

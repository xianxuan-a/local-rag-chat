"""Opt-in destructive-isolated Docker Compose smoke test.

Run with ``RUN_DOCKER_COMPOSE_SMOKE=1``. The test uses a unique Compose
project and only removes the named volume created for that project.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_SMOKE = os.getenv("RUN_DOCKER_COMPOSE_SMOKE") == "1"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run(
    docker: str,
    project: str,
    env_file: Path,
    *arguments: str,
    check: bool = True,
    timeout: float = 600,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            docker,
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(env_file),
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"docker compose {' '.join(arguments)} failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_until_ready(base_url: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, payload = _request_json(f"{base_url}/health/ready")
            if status == 200 and payload["data"]["status"] == "ready":
                return
        except (OSError, URLError, ValueError, KeyError) as error:
            last_error = error
        time.sleep(1)
    raise AssertionError(f"backend did not become ready: {last_error}")


@pytest.mark.skipif(
    not RUN_SMOKE,
    reason="set RUN_DOCKER_COMPOSE_SMOKE=1 to run isolated Docker smoke",
)
def test_fresh_volume_restart_and_invalid_production_config(
    tmp_path: Path,
) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Docker CLI is required for the requested smoke test")
    project = f"local-rag-chat-smoke-{uuid4().hex[:10]}"
    backend_port = _free_port()
    frontend_port = _free_port()
    bootstrap_secret = "bootstrap-" + uuid4().hex + uuid4().hex
    env_file = tmp_path / "compose-smoke.env"
    env_file.write_text(
        "\n".join(
            (
                f"BACKEND_PORT={backend_port}",
                f"FRONTEND_PORT={frontend_port}",
                "PIP_INDEX_URL="
                + os.getenv(
                    "COMPOSE_SMOKE_PIP_INDEX_URL",
                    "https://pypi.org/simple",
                ),
                f"JWT_SECRET=jwt-{uuid4().hex}{uuid4().hex}",
                f"METRICS_SCRAPE_TOKEN=metrics-{uuid4().hex}{uuid4().hex}",
                f"BACKUP_SIGNING_KEY=backup-{uuid4().hex}{uuid4().hex}",
                f"BOOTSTRAP_SECRET={bootstrap_secret}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    base_url = f"http://127.0.0.1:{backend_port}"
    password = "compose-test-password-123"

    try:
        if os.getenv("COMPOSE_SMOKE_SKIP_BUILD") != "1":
            _run(
                docker,
                project,
                env_file,
                "build",
                "--no-cache",
                "backend",
                timeout=900,
            )
        _run(docker, project, env_file, "up", "-d", "backend")
        _wait_until_ready(base_url)
        live_status, live = _request_json(f"{base_url}/health/live")
        assert live_status == 200
        assert live["data"] == {"status": "live"}

        bootstrap_status, _ = _request_json(
            f"{base_url}/api/auth/bootstrap",
            method="POST",
            headers={"X-Bootstrap-Secret": bootstrap_secret},
            payload={
                "username": "compose-admin",
                "email": "compose-admin@example.com",
                "password": password,
            },
        )
        assert bootstrap_status == 200

        _run(docker, project, env_file, "restart", "backend")
        _wait_until_ready(base_url)
        login_status, _ = _request_json(
            f"{base_url}/api/auth/login",
            method="POST",
            payload={"identity": "compose-admin", "password": password},
        )
        assert login_status == 200

        _run(docker, project, env_file, "down")
        _run(docker, project, env_file, "up", "-d")
        _wait_until_ready(base_url)
        login_status, _ = _request_json(
            f"{base_url}/api/auth/login",
            method="POST",
            payload={"identity": "compose-admin", "password": password},
        )
        assert login_status == 200

        invalid = _run(
            docker,
            project,
            env_file,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "AUTH_REQUIRED=false",
            "backend",
            check=False,
            timeout=60,
        )
        assert invalid.returncode != 0
        assert "AUTH_REQUIRED" in invalid.stdout + invalid.stderr
    finally:
        _run(
            docker,
            project,
            env_file,
            "down",
            "--volumes",
            "--remove-orphans",
            check=False,
            timeout=120,
        )

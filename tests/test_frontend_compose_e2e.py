"""Opt-in isolated Vue/Nginx/FastAPI Compose acceptance test.

Run with ``RUN_DOCKER_FRONTEND_E2E=1``. Every run uses a unique Compose
project and fresh named volume. The backend keeps the real API, SQLite,
Chroma, migrations, and worker, while substituting only deterministic local
embedding and chat providers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
RUN_E2E = os.getenv("RUN_DOCKER_FRONTEND_E2E") == "1"
BOOTSTRAP_SECRET = "G5hczu_T4XWOLbPX2dYBzEDOQhP07qOW"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _compose(
    docker: str,
    project: str,
    env_file: Path,
    *arguments: str,
    check: bool = True,
    timeout: float = 900,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            docker,
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(env_file),
            "-f",
            str(PROJECT_ROOT / "docker-compose.yml"),
            "-f",
            str(PROJECT_ROOT / "docker-compose.e2e.yml"),
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


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def _wait_for_frontend(base_url: str, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, _, body = _request(f"{base_url}/healthz")
            if status == 200 and body == b"ok\n":
                return
        except (OSError, URLError) as error:
            last_error = error
        time.sleep(1)
    raise AssertionError(f"frontend did not become ready: {last_error}")


def _json(body: bytes) -> dict[str, object]:
    value = json.loads(body.decode("utf-8"))
    assert isinstance(value, dict)
    return value


def _run_playwright(base_url: str, token: str, *, backend_down: bool) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise AssertionError("npm is required for the requested frontend E2E")
    environment = os.environ.copy()
    environment.update(
        {
            "NEXUS_E2E_BASE_URL": base_url,
            "NEXUS_REAL_API_E2E": "1",
            "NEXUS_REAL_API_ACCESS_TOKEN": token,
            "NEXUS_EXPECT_BACKEND_DOWN": "1" if backend_down else "0",
            "NEXUS_REAL_API_KB_NAME": f"compose-real-{uuid4().hex[:10]}",
        }
    )
    result = subprocess.run(
        [npm, "run", "test:e2e", "--", "real-api.spec.ts"],
        cwd=FRONTEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(
    not RUN_E2E,
    reason="set RUN_DOCKER_FRONTEND_E2E=1 to run isolated frontend E2E",
)
def test_vue_real_container_proxy_and_browser_chain(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Docker CLI is required for the requested frontend E2E")

    project = f"local-rag-vue-e2e-{uuid4().hex[:10]}"
    backend_port = _free_port()
    frontend_port = _free_port()
    env_file = tmp_path / "frontend-e2e.env"
    env_file.write_text(
        "\n".join(
            (
                f"BACKEND_PORT={backend_port}",
                f"FRONTEND_PORT={frontend_port}",
                f"JWT_SECRET=jwt-{uuid4().hex}{uuid4().hex}",
                f"METRICS_SCRAPE_TOKEN=metrics-{uuid4().hex}{uuid4().hex}",
                f"BACKUP_SIGNING_KEY=backup-{uuid4().hex}{uuid4().hex}",
                f"BOOTSTRAP_SECRET=bootstrap-{uuid4().hex}{uuid4().hex}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    base_url = f"http://127.0.0.1:{frontend_port}"

    try:
        if os.getenv("FRONTEND_E2E_SKIP_BUILD") != "1":
            _compose(docker, project, env_file, "build", "--no-cache", "frontend")
        _compose(docker, project, env_file, "up", "-d", "frontend")
        _wait_for_frontend(base_url)

        for route in ("/dashboard", "/chat", "/knowledge-bases", "/settings"):
            status, headers, body = _request(f"{base_url}{route}")
            assert status == 200
            assert b'<div id="app"></div>' in body
            assert "no-cache" in headers.get("Cache-Control", "")
            assert headers.get("X-Content-Type-Options") == "nosniff"
            assert headers.get("X-Frame-Options") == "DENY"
            assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

        _, _, index_body = _request(f"{base_url}/")
        asset_match = re.search(rb'src="(/assets/[^"]+\.js)"', index_body)
        assert asset_match is not None
        asset_path = asset_match.group(1).decode("ascii")
        status, headers, _ = _request(
            f"{base_url}{asset_path}", headers={"Accept-Encoding": "gzip"}
        )
        assert status == 200
        assert "immutable" in headers.get("Cache-Control", "")
        assert headers.get("Content-Encoding") == "gzip"
        assert "javascript" in headers.get("Content-Type", "")

        status, headers, body = _request(f"{base_url}/api/knowledge-bases")
        assert status == 401
        assert "json" in headers.get("Content-Type", "")
        assert b"<html" not in body.lower()

        status, headers, body = _request(
            f"{base_url}/api/chat/stream", method="POST", payload={}
        )
        assert status == 401
        assert headers.get("X-Accel-Buffering") == "no"
        assert b"<html" not in body.lower()

        status, headers, body = _request(f"{base_url}/api/not-a-real-route")
        assert status == 404
        assert "json" in headers.get("Content-Type", "")
        assert b"<html" not in body.lower()

        status, headers, body = _request(f"{base_url}/api/_test/error")
        assert status == 500
        assert "json" in headers.get("Content-Type", "")
        assert b"<html" not in body.lower()

        status, _, body = _request(
            f"{base_url}/api/auth/bootstrap",
            method="POST",
            headers={"X-Bootstrap-Secret": BOOTSTRAP_SECRET},
            payload={
                "username": "compose-real-admin",
                "email": "compose-real-admin@example.com",
                "password": "compose-real-password-123",
            },
        )
        assert status == 200, body
        status, _, body = _request(
            f"{base_url}/api/auth/login",
            method="POST",
            payload={
                "identity": "compose-real-admin",
                "password": "compose-real-password-123",
            },
        )
        assert status == 200, body
        token = str(_json(body)["data"]["access_token"])  # type: ignore[index]

        for forbidden_path in (
            "/app/src",
            "/app/node_modules",
            "/usr/share/nginx/html/src",
            "/usr/share/nginx/html/tests",
            "/usr/share/nginx/html/node_modules",
        ):
            _compose(
                docker,
                project,
                env_file,
                "exec",
                "-T",
                "frontend",
                "test",
                "!",
                "-e",
                forbidden_path,
            )

        _run_playwright(base_url, token, backend_down=False)

        _compose(docker, project, env_file, "stop", "backend")
        status, _, body = _request(f"{base_url}/api/knowledge-bases")
        assert status in {502, 504}
        assert b'<div id="app"></div>' not in body
        _run_playwright(base_url, token, backend_down=True)
    finally:
        _compose(
            docker,
            project,
            env_file,
            "down",
            "--volumes",
            "--remove-orphans",
            check=False,
            timeout=180,
        )

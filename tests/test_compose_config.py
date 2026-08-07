"""Docker Compose production contract tests that do not require a daemon."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = (
    "JWT_SECRET",
    "METRICS_SCRAPE_TOKEN",
    "BACKUP_SIGNING_KEY",
    "BOOTSTRAP_SECRET",
)


def _compose_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PIP_INDEX_URL", None)
    for index, name in enumerate(SECRET_NAMES):
        environment[name] = f"compose-test-{index}-" + ("x" * 40)
    return environment


def _run_compose(*arguments: str, environment: dict[str, str]):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")
    return subprocess.run(
        [docker, "compose", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_compose_expands_to_authenticated_migration_gated_backend() -> None:
    result = _run_compose(
        "config", "--format", "json", environment=_compose_environment()
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    backend = config["services"]["backend"]
    migrate = config["services"]["migrate"]

    assert backend["environment"]["ENVIRONMENT"] == "production"
    assert backend["environment"]["AUTH_REQUIRED"] == "true"
    assert backend["environment"]["HOST"] == "0.0.0.0"
    assert backend["command"] == ["python", "run.py"]
    assert backend["build"]["args"]["PIP_INDEX_URL"] == (
        "https://pypi.org/simple"
    )
    assert backend["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert not migrate.get("profiles")
    assert migrate["command"] == ["python", "scripts/run_migrations.py"]
    assert "/health/ready" in " ".join(backend["healthcheck"]["test"])


def test_compose_uses_vue_real_frontend_and_profiles_legacy_streamlit() -> None:
    result = _run_compose(
        "--profile",
        "legacy",
        "config",
        "--format",
        "json",
        environment=_compose_environment(),
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    frontend = services["frontend"]
    legacy = services["legacy-ui"]

    assert frontend["image"] == "local-rag-chat-frontend:0.1.0"
    assert Path(frontend["build"]["context"]).name == "frontend"
    assert frontend["build"]["args"]["VITE_API_MODE"] == "real"
    assert frontend["build"]["args"]["VITE_API_BASE_URL"] == "/"
    assert frontend["ports"][0]["target"] == 8080
    assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
    assert legacy["profiles"] == ["legacy"]
    assert legacy["ports"][0]["published"] == "8502"
    assert "streamlit" in legacy["command"]


def test_frontend_image_and_nginx_contract() -> None:
    backend_dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(
        encoding="utf-8"
    )
    dockerfile = (PROJECT_ROOT / "frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    nginx = (PROJECT_ROOT / "frontend" / "nginx.conf").read_text(
        encoding="utf-8"
    )

    assert 'CMD ["python", "run.py"]' in backend_dockerfile
    assert "FROM node:24-alpine AS build" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "npm run build:real" in dockerfile
    assert "npm run audit:real" in dockerfile
    assert "nginxinc/nginx-unprivileged" in dockerfile
    assert "COPY --from=build /app/dist-real/" in dockerfile
    assert "proxy_pass http://fastapi_backend" in nginx
    assert "location /api/" in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_request_buffering off" in nginx
    assert "postpone_output 0" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "immutable" in nginx
    assert "X-Content-Type-Options \"nosniff\"" in nginx


def test_compose_rejects_a_missing_production_secret(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for name in SECRET_NAMES:
        environment.pop(name, None)
    env_file = tmp_path / "missing-secret.env"
    env_file.write_text(
        "\n".join(
            f"{name}={'x' * 40}"
            for name in SECRET_NAMES
            if name != "BOOTSTRAP_SECRET"
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_compose(
        "--env-file",
        str(env_file),
        "config",
        "-q",
        environment=environment,
    )

    assert result.returncode != 0
    assert "BOOTSTRAP_SECRET" in result.stderr

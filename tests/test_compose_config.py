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
    assert backend["environment"]["AUTH_RATE_LIMIT_ENABLED"] == "true"
    assert backend["environment"]["LOGIN_RATE_LIMIT_COMBINATION_ATTEMPTS"] == "5"
    assert backend["environment"]["TRUSTED_PROXY_CIDRS"] == "[]"
    assert backend["environment"]["TRUSTED_PROXY_HOSTS"] == '["frontend"]'
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
    launcher = (PROJECT_ROOT / "run.py").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    nginx = (PROJECT_ROOT / "frontend" / "nginx.conf").read_text(
        encoding="utf-8"
    )

    assert 'CMD ["python", "run.py"]' in backend_dockerfile
    assert "access_log=False" in launcher
    assert "AS dependencies" in backend_dockerfile
    assert "AS runtime" in backend_dockerfile
    assert "COPY requirements.txt requirements.lock ./" in backend_dockerfile
    assert "-r requirements.lock" in backend_dockerfile
    assert "-r requirements.txt" not in backend_dockerfile
    assert "COPY . ." not in backend_dockerfile
    assert "FROM node:24-alpine AS build" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "npm run build" in dockerfile
    assert "npm run audit:real" in dockerfile
    assert "nginxinc/nginx-unprivileged" in dockerfile
    assert "COPY --from=build /app/dist-real/" in dockerfile
    assert "proxy_pass http://fastapi_backend" in nginx
    assert 'proxy_set_header Forwarded ""' in nginx
    assert "location /api/" in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_request_buffering off" in nginx
    assert "postpone_output 0" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "immutable" in nginx
    assert "X-Content-Type-Options \"nosniff\"" in nginx


def test_frontend_build_defaults_to_real_and_mock_is_explicit() -> None:
    package = json.loads(
        (PROJECT_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    scripts = package["scripts"]
    vite_config = (PROJECT_ROOT / "frontend" / "vite.config.ts").read_text(
        encoding="utf-8"
    )
    audit = (
        PROJECT_ROOT / "frontend" / "scripts" / "audit-real-build.mjs"
    ).read_text(encoding="utf-8")
    root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    frontend_readme = (PROJECT_ROOT / "frontend" / "README.md").read_text(
        encoding="utf-8"
    )
    github_workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "frontend-build.yml"
    ).read_text(encoding="utf-8")

    assert scripts["build"] == "npm run build:real"
    assert scripts["build:mock"] == "vite build --mode mock"
    assert scripts["build:real"] == "node scripts/build-real.mjs"
    assert scripts["ci:build"] == (
        "npm run build && npm run audit:real && npm run build:mock"
    )
    assert "VITE_API_MODE must be explicitly set to mock or real" in vite_config
    assert "BUILD_MODE=${apiMode}" in vite_config
    assert "build-meta.json" in vite_config
    assert "production_deployable: apiMode === 'real'" in vite_config
    assert "metadata.build_mode !== 'real'" in audit
    assert "mockRuntimeAdapter" in audit
    assert "src/mocks/" in audit
    assert "permissions:\n  contents: read" in github_workflow
    assert 'NODE_VERSION: "24.14.0"' in github_workflow
    assert "node-version: ${{ env.NODE_VERSION }}" in github_workflow
    assert "run: npm ci" in github_workflow
    assert "npm run test:unit --" in github_workflow
    assert "run: npm run ci:build" in github_workflow
    for documentation in (root_readme, frontend_readme):
        assert "npm run build" in documentation
        assert "npm run audit:real" in documentation
        assert "npm run build:mock" in documentation
        assert "build-meta.json" in documentation


def test_frontend_build_rejects_missing_and_unknown_modes() -> None:
    node = shutil.which("node")
    vite = PROJECT_ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite.is_file():
        pytest.skip("frontend npm dependencies are not installed")

    environment = os.environ.copy()
    environment.pop("VITE_API_MODE", None)
    missing = subprocess.run(
        [node, str(vite), "build", "--mode", "production"],
        cwd=PROJECT_ROOT / "frontend",
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    environment["VITE_API_MODE"] = "unexpected"
    unknown = subprocess.run(
        [node, str(vite), "build", "--mode", "unexpected"],
        cwd=PROJECT_ROOT / "frontend",
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert missing.returncode != 0
    assert unknown.returncode != 0
    for result in (missing, unknown):
        assert "VITE_API_MODE must be explicitly set to mock or real" in (
            result.stdout + result.stderr
        )


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

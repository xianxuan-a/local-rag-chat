"""Contracts that keep Docker build inputs minimal and secret-free."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _active_patterns(path: Path) -> list[str]:
    return [
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def test_backend_context_is_deny_by_default_with_runtime_allowlist() -> None:
    patterns = _active_patterns(PROJECT_ROOT / ".dockerignore")

    assert patterns[0] == "**"
    assert {
        "!requirements.lock",
        "!run.py",
        "!alembic.ini",
        "!app/**",
        "!alembic/**",
        "!scripts/*.py",
        "!ui/**",
    } <= set(patterns)
    assert not any(
        pattern.startswith(("!frontend", "!tests", "!data", "!.env"))
        for pattern in patterns
    )
    assert "**/__pycache__/" in patterns
    assert "**/*.py[cod]" in patterns


def test_backend_dockerfile_uses_locked_dependency_stage_and_explicit_copy() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "AS dependencies" in dockerfile
    assert "AS runtime" in dockerfile
    assert "COPY requirements.txt requirements.lock ./" in dockerfile
    assert "-r requirements.lock" in dockerfile
    assert "python -m pip check" in dockerfile
    assert "--prefix=/install" in dockerfile
    assert "COPY --from=dependencies /install/ /usr/local/" in dockerfile
    assert "COPY --chown=app:app app ./app" in dockerfile
    assert "COPY --chown=app:app alembic ./alembic" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "COPY ./" not in dockerfile


def test_frontend_context_and_dockerfile_exclude_host_and_test_inputs() -> None:
    frontend = PROJECT_ROOT / "frontend"
    patterns = _active_patterns(frontend / ".dockerignore")
    dockerfile = (frontend / "Dockerfile").read_text(encoding="utf-8")

    assert patterns[0] == "**"
    assert {
        "!package-lock.json",
        "!src/**",
        "!public/**",
        "!scripts/build-real.mjs",
        "!scripts/audit-real-build.mjs",
        "!nginx.conf",
    } <= set(patterns)
    assert not any(
        pattern.startswith(
            ("!node_modules", "!dist", "!artifacts", "!e2e", "!.env")
        )
        for pattern in patterns
    )
    assert "**/*.spec.ts" in patterns
    assert "src/mocks/**" in patterns
    assert "src/api/adapters/mockRuntimeAdapter.ts" in patterns
    assert "RUN npm ci" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "COPY src ./src" in dockerfile
    assert "COPY --from=build /app/dist-real/" in dockerfile

"""Static fail-closed contract for GitHub CI and production gates."""

from __future__ import annotations

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_PATH = PROJECT_ROOT / ".github" / "workflows" / "frontend-build.yml"
RELEASE_PATH = PROJECT_ROOT / ".github" / "workflows" / "production-gate.yml"
PIN_PATTERN = re.compile(r"uses:\s+[^\s@]+@[0-9a-f]{40}\s+#")


def validate_workflows(ci: str, release: str) -> None:
    required_ci = (
        "python-quality:",
        "backend:",
        "migrations:",
        "frontend:",
        "builds:",
        "compose:",
        "docker-smoke:",
        "mock-e2e:",
        "real-e2e:",
        "security:",
        "required-checks:",
        "python -m pip install --requirement requirements-dev.lock",
        "python -m ruff check .",
        "python -m pip check",
        "python -m compileall",
        "python -m pytest",
        "npm run type-check",
        "npm run format:check",
        "npm run ci:build",
        "bundle-report-real.json",
        "docker compose config -q",
        "RUN_DOCKER_COMPOSE_SMOKE: \"1\"",
        "RUN_DOCKER_FRONTEND_E2E: \"1\"",
        "python scripts/verify_chroma_boundary.py",
    )
    required_release = (
        "workflow_dispatch:",
        "schedule:",
        "environment: staging",
        "secrets.DASHSCOPE_API_KEY",
        "RUN_DASHSCOPE_SMOKE: \"1\"",
        "release-security:",
        "python scripts/verify_security_policy.py",
        "python scripts/verify_chroma_boundary.py",
        "ignore-vulns: PYSEC-2026-311",
        "recovery-drill:",
        "production-images:",
        "--build-arg VCS_REF=${GITHUB_SHA}",
        "create_release_evidence.py",
        "production-evidence-${{ github.sha }}",
    )
    for fragment in required_ci:
        if fragment not in ci:
            raise ValueError(f"CI workflow missing required gate: {fragment}")
    for fragment in required_release:
        if fragment not in release:
            raise ValueError(f"release workflow missing required gate: {fragment}")
    combined = ci + "\n" + release
    for forbidden in ("continue-on-error", "pull_request_target", "write-all"):
        if forbidden in combined:
            raise ValueError(f"workflow contains forbidden setting: {forbidden}")
    for line in combined.splitlines():
        if "uses:" in line and not PIN_PATTERN.search(line):
            raise ValueError(f"GitHub Action is not pinned to a commit: {line.strip()}")
    if "pull_request:" in release:
        raise ValueError("production workflow must never receive PR secrets")


def main() -> int:
    validate_workflows(
        CI_PATH.read_text(encoding="utf-8"),
        RELEASE_PATH.read_text(encoding="utf-8"),
    )
    print("ci_contract=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

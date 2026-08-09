"""CI/CD contracts that fail closed under workflow regressions."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from scripts.create_release_evidence import REQUIRED_CHECKS, build_evidence
from scripts.verify_ci_contract import validate_workflows
from scripts.verify_security_policy import verify_policy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_PATH = PROJECT_ROOT / ".github" / "workflows" / "frontend-build.yml"
RELEASE_PATH = PROJECT_ROOT / ".github" / "workflows" / "production-gate.yml"
FRONTEND_PACKAGE_PATH = PROJECT_ROOT / "frontend" / "package.json"
PRETTIER_IGNORE_PATH = PROJECT_ROOT / "frontend" / ".prettierignore"


def _workflows() -> tuple[str, str]:
    return (
        CI_PATH.read_text(encoding="utf-8"),
        RELEASE_PATH.read_text(encoding="utf-8"),
    )


def test_ci_contract_covers_required_checks_and_security_boundaries() -> None:
    ci, release = _workflows()

    validate_workflows(ci, release)

    assert "permissions:\n  contents: read" in ci
    assert "permissions:\n  contents: read" in release
    assert "AUTH_REQUIRED=false" not in ci
    assert "secrets.DASHSCOPE_API_KEY" not in ci
    assert "pull_request:" not in release
    assert "environment: staging" in release
    assert "include-hidden-files: true" in release
    assert ".env" not in release
    assert "data/" not in release


@pytest.mark.parametrize(
    "broken_fragment",
    (
        "python -m pytest",
        "npm run type-check",
        "npm run format:check",
        "npm run ci:build",
        "docker compose config -q",
        'RUN_DOCKER_FRONTEND_E2E: "1"',
    ),
)
def test_ci_contract_rejects_removed_required_gate(broken_fragment: str) -> None:
    ci, release = _workflows()

    with pytest.raises(ValueError, match="missing required gate"):
        validate_workflows(ci.replace(broken_fragment, "REMOVED"), release)


def test_ci_contract_rejects_unpinned_action_and_failure_masking() -> None:
    ci, release = _workflows()

    with pytest.raises(ValueError, match="not pinned"):
        validate_workflows(ci.replace("@3d3c42e5aac5ba805825da76410c181273ba90b1", "@v7", 1), release)
    with pytest.raises(ValueError, match="forbidden"):
        validate_workflows(ci + "\ncontinue-on-error: true\n", release)


def test_frontend_format_gate_is_narrow_and_fail_closed() -> None:
    package = json.loads(FRONTEND_PACKAGE_PATH.read_text(encoding="utf-8"))
    format_check = package["scripts"]["format:check"]
    patterns = {
        line.strip()
        for line in PRETTIER_IGNORE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "verify-format-contract.mjs" in format_check
    assert "prettier --check ." in format_check
    assert {
        "node_modules",
        ".vite",
        "dist",
        "dist-real",
        "dist-mock",
        "artifacts",
        "coverage",
        "playwright-report",
        "test-results",
        "package-lock.json",
    } == patterns
    assert patterns.isdisjoint(
        {
            "src",
            "src/**",
            "e2e",
            "e2e/**",
            "*.ts",
            "*.vue",
            "package.json",
            "vite.config.ts",
        }
    )


def test_release_evidence_requires_every_gate_and_commit_bound_images() -> None:
    commit_sha = "a" * 40
    checks = {name: "passed" for name in REQUIRED_CHECKS}

    evidence = build_evidence(
        commit_sha=commit_sha,
        repository="xianxuan-a/local-rag-chat",
        checks=checks,
    )

    assert evidence["production_candidate"] is True
    assert evidence["commit_sha"] == commit_sha
    assert evidence["images"] == {
        "backend": f"local-rag-chat:{commit_sha}",
        "frontend": f"local-rag-chat-frontend:{commit_sha}",
    }
    serialized = json.dumps(evidence)
    assert "DASHSCOPE_API_KEY" not in serialized
    assert ".env" not in serialized

    for failed_check in REQUIRED_CHECKS:
        blocked = checks | {failed_check: "failed"}
        with pytest.raises(ValueError, match="production candidate blocked"):
            build_evidence(
                commit_sha=commit_sha,
                repository="xianxuan-a/local-rag-chat",
                checks=blocked,
            )


def test_security_exception_is_narrow_current_and_time_limited() -> None:
    assert verify_policy(today=date(2026, 8, 8)) == ["PYSEC-2026-311"]
    with pytest.raises(ValueError, match="expired"):
        verify_policy(today=date(2026, 9, 1))

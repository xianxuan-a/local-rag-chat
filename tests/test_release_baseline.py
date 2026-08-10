"""Contracts for a complete, private, reproducible Git release tree."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

from app.database.migrations import head_revision
from scripts.verify_release_baseline import (
    EXPECTED_IGNORED_PATHS,
    EXPECTED_TRACKABLE_PATHS,
    PROJECT_ROOT,
    audit_repository,
    is_ignored,
    readme_link_errors,
    scan_secret_contents,
)


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = line.split(";", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", requirement)
        assert match is not None, f"dependency is not exactly pinned: {line}"
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        pins[name] = match.group(2)
    return pins


def test_release_baseline_audit_passes_for_candidate_tree() -> None:
    report = audit_repository(PROJECT_ROOT)
    assert report["ok"], report["errors"]
    assert report["counts"]["untracked_not_ignored"] == 0
    assert report["counts"]["tracked"] >= 350


def test_ignore_contract_protects_runtime_without_hiding_sources() -> None:
    for path in EXPECTED_IGNORED_PATHS:
        assert is_ignored(PROJECT_ROOT, path), path
    for path in EXPECTED_TRACKABLE_PATHS:
        assert not is_ignored(PROJECT_ROOT, path), path


def test_secret_scanner_detects_failure_and_accepts_safe_templates() -> None:
    secret_name = b"JWT_" + b"SECRET"
    private_header = b"-----BEGIN " + b"PRIVATE KEY-----"
    provider_token = b"sk-" + (b"a" * 32)
    unsafe = {
        "config.env": secret_name + b"=" + (b"x" * 40),
        "certificate.txt": private_header,
        "provider.txt": provider_token,
    }
    rules = {finding["rule"] for finding in scan_secret_contents(unsafe)}
    assert {
        "nonempty_secret_assignment",
        "private_key",
        "provider_token",
    } <= rules

    safe = {
        ".env.example": secret_name + b"=\n",
        "docker-compose.yml": secret_name + b"=${" + secret_name + b":?required}\n",
        "tests/fakes.py": secret_name + b"='test-only-value'\n",
    }
    assert scan_secret_contents(safe) == []


def test_direct_python_dependencies_are_present_in_complete_lock() -> None:
    direct = _pins(PROJECT_ROOT / "requirements.txt")
    locked = _pins(PROJECT_ROOT / "requirements.lock")
    assert len(locked) >= 100
    assert direct.items() <= locked.items()


def test_readme_local_links_and_migration_head_are_release_tracked() -> None:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    tracked = set(result.stdout.splitlines())
    assert readme_link_errors(PROJECT_ROOT, tracked) == []
    assert "alembic/versions/0007_retrieval_modes.py" in tracked
    assert "alembic/versions/0008_user_identities.py" in tracked
    assert "alembic/versions/0009_user_admin_audit.py" in tracked
    assert head_revision() == "0009_user_admin_audit"

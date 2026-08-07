"""Audit the tracked release tree without reading ignored user data."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024
LARGE_FILE_WARNING_BYTES = 1024 * 1024

REQUIRED_PATHS = frozenset(
    {
        ".dockerignore",
        ".env.example",
        ".gitattributes",
        ".gitignore",
        "Dockerfile",
        "README.md",
        "alembic.ini",
        "docker-compose.e2e.yml",
        "docker-compose.yml",
        "docs/release-baseline.md",
        "frontend/.dockerignore",
        "frontend/.env.development",
        "frontend/.env.example",
        "frontend/.env.mock",
        "frontend/.env.real",
        "frontend/.env.test",
        "frontend/.gitignore",
        "frontend/Dockerfile",
        "frontend/README.md",
        "frontend/nginx.conf",
        "frontend/package-lock.json",
        "frontend/package.json",
        "frontend/playwright.config.ts",
        "frontend/vite.config.ts",
        "frontend/vitest.config.ts",
        "requirements.lock",
        "requirements.txt",
        "run.py",
        "scripts/verify_release_baseline.py",
        "tests/test_release_baseline.py",
        "启动项目.cmd",
        "停止项目.cmd",
        "查看状态.cmd",
    }
)

REQUIRED_PREFIX_MINIMUMS = {
    "alembic/versions/": 1,
    "app/": 1,
    "frontend/e2e/": 1,
    "frontend/src/": 1,
    "scripts/": 1,
    "tests/": 1,
}

EXPECTED_IGNORED_PATHS = (
    ".env",
    ".env.production",
    ".secrets/private.txt",
    ".venv/pyvenv.cfg",
    "data/backups/release.zip",
    "data/chroma/chroma.sqlite3",
    "data/metadata/local_rag_chat.db",
    "data/uploads/private.pdf",
    "frontend/.env.real.local",
    "frontend/dist-real/index.html",
    "frontend/node_modules/example/index.js",
    "frontend/playwright-report/index.html",
    "frontend/test-results/result.json",
    "logs/app.log",
    "server.pid",
)

EXPECTED_TRACKABLE_PATHS = (
    ".env.example",
    "alembic/versions/0007_retrieval_modes.py",
    "app/core/config.py",
    "frontend/.env.real",
    "frontend/src/main.ts",
    "requirements.lock",
    "tests/test_release_baseline.py",
)

README_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*[\"']?(DASHSCOPE_API_KEY|WEB_SEARCH_API_KEY|JWT_SECRET|"
    r"METRICS_SCRAPE_TOKEN|BACKUP_SIGNING_KEY|BOOTSTRAP_SECRET)"
    r"[\"']?[ \t]*[:=][ \t]*[\"']?([^\"'\s#]+)",
    re.IGNORECASE | re.MULTILINE,
)
ASSIGNMENT_SUFFIXES = {
    ".cfg",
    ".cmd",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".properties",
    ".ps1",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = (
    (
        "private_key",
        re.compile(
            "-----BEGIN "
            r"(?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
        ),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ),
    (
        "provider_token",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "credential_url",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
            r"[^\s/:@]+:[^\s/@]+@",
            re.IGNORECASE,
        ),
    ),
)
LOCAL_MACHINE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^/\s]+/(?:Desktop|Downloads)/"),
)


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def _git_paths(root: Path, *arguments: str) -> list[str]:
    return [
        line
        for line in _git(root, *arguments).stdout.splitlines()
        if line
    ]


def is_ignored(root: Path, path: str) -> bool:
    return (
        _git(
            root,
            "check-ignore",
            "--no-index",
            "-q",
            "--",
            path,
            check=False,
        ).returncode
        == 0
    )


def classify_ignored_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if re.search(r"(^|/)(node_modules|\.venv|venv|env)/", normalized):
        return "dependencies"
    if re.search(
        r"(__pycache__/|\.py[cod]$|\.pytest_cache/|\.mypy_cache/|\.ruff_cache/)",
        normalized,
    ):
        return "python_cache"
    if re.search(r"^frontend/(dist[^/]*/|\.vite/)", normalized):
        return "frontend_build"
    if re.search(
        r"(playwright-report/|test-results/|artifacts/|coverage/|htmlcov/)",
        normalized,
    ):
        return "test_artifacts"
    if re.search(
        r"^(data/|logs/)|\.(db|sqlite|sqlite3)(-|$)|\.log$|\.pid$",
        normalized,
    ):
        return "runtime_data"
    if re.search(r"(^|/)\.env($|\.)|\.local$|\.local-rag", normalized):
        return "local_environment"
    if re.search(r"(^|/)(\.idea|\.vscode)/", normalized):
        return "editor"
    return "other"


def scan_secret_contents(contents: dict[str, bytes]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path, raw in contents.items():
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for rule, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "rule": rule,
                        "path": path,
                        "line": text.count("\n", 0, match.start()) + 1,
                    }
                )
        suffix = Path(path).suffix.lower()
        if not path.startswith("tests/") and (
            suffix in ASSIGNMENT_SUFFIXES or Path(path).name.startswith(".env")
        ):
            for match in SENSITIVE_ASSIGNMENT_RE.finditer(text):
                value = match.group(2).strip()
                if not value or value.startswith("${") or value.startswith("<"):
                    continue
                findings.append(
                    {
                        "rule": "nonempty_secret_assignment",
                        "path": path,
                        "line": text.count("\n", 0, match.start()) + 1,
                    }
                )
        for pattern in LOCAL_MACHINE_PATH_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "rule": "local_machine_path",
                        "path": path,
                        "line": text.count("\n", 0, match.start()) + 1,
                    }
                )
    return findings


def tracked_contents(root: Path, tracked: set[str]) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for path in sorted(tracked):
        candidate = root / Path(path)
        if candidate.is_file():
            contents[path] = candidate.read_bytes()
    return contents


def readme_link_errors(root: Path, tracked: set[str]) -> list[str]:
    errors: list[str] = []
    for readme in sorted(path for path in tracked if Path(path).name == "README.md"):
        text = (root / readme).read_text(encoding="utf-8")
        for match in README_LINK_RE.finditer(text):
            target = unquote(match.group(1)).split("#", 1)[0].split("?", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            resolved = ((root / readme).parent / target).resolve()
            try:
                relative = resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                errors.append(f"{readme}: link escapes repository: {target}")
                continue
            if relative not in tracked:
                errors.append(f"{readme}: untracked or missing link: {target}")
    return errors


def audit_repository(root: Path, *, require_clean: bool = False) -> dict[str, object]:
    root = root.resolve()
    tracked = set(_git_paths(root, "ls-files"))
    untracked = _git_paths(root, "ls-files", "--others", "--exclude-standard")
    ignored = _git_paths(
        root, "ls-files", "--others", "--ignored", "--exclude-standard"
    )
    errors: list[str] = []
    warnings: list[str] = []

    missing = sorted(REQUIRED_PATHS - tracked)
    errors.extend(f"required path is not tracked: {path}" for path in missing)
    for prefix, minimum in REQUIRED_PREFIX_MINIMUMS.items():
        count = sum(path.startswith(prefix) for path in tracked)
        if count < minimum:
            errors.append(f"tracked prefix {prefix!r} has {count}, expected >= {minimum}")

    for path in EXPECTED_IGNORED_PATHS:
        if not is_ignored(root, path):
            errors.append(f"runtime/private path is not ignored: {path}")
    for path in EXPECTED_TRACKABLE_PATHS:
        if path not in tracked:
            errors.append(f"source/config path is not tracked: {path}")
        elif is_ignored(root, path):
            errors.append(f"source/config path is covered by ignore rules: {path}")

    errors.extend(readme_link_errors(root, tracked))
    secret_findings = scan_secret_contents(tracked_contents(root, tracked))
    errors.extend(
        f"{finding['rule']} at {finding['path']}:{finding['line']}"
        for finding in secret_findings
    )

    large_files: list[dict[str, object]] = []
    for path in sorted(tracked):
        candidate = root / Path(path)
        if not candidate.is_file():
            continue
        size = candidate.stat().st_size
        if size >= LARGE_FILE_WARNING_BYTES:
            large_files.append({"path": path, "bytes": size})
        if size > MAX_TRACKED_FILE_BYTES:
            errors.append(f"tracked file exceeds 10 MiB: {path} ({size} bytes)")
    if large_files:
        warnings.append(f"{len(large_files)} tracked files are at least 1 MiB")

    if untracked:
        errors.extend(f"untracked release candidate file: {path}" for path in untracked)
    if require_clean:
        status = _git(
            root, "status", "--short", "--untracked-files=all"
        ).stdout.strip()
        if status:
            errors.append("release worktree is not clean")

    return {
        "ok": not errors,
        "head": _git(root, "rev-parse", "HEAD").stdout.strip(),
        "counts": {
            "tracked": len(tracked),
            "untracked_not_ignored": len(untracked),
            "ignored": len(ignored),
            "ignored_by_category": dict(
                sorted(Counter(classify_ignored_path(path) for path in ignored).items())
            ),
        },
        "large_files": large_files,
        "errors": errors,
        "warnings": warnings,
    }


def _print_human(report: dict[str, object]) -> None:
    counts = report["counts"]
    assert isinstance(counts, dict)
    print(f"release_head={report['head']}")
    print(f"tracked={counts['tracked']}")
    print(f"untracked_not_ignored={counts['untracked_not_ignored']}")
    print(f"ignored={counts['ignored']}")
    categories = counts["ignored_by_category"]
    assert isinstance(categories, dict)
    for name, count in categories.items():
        print(f"ignored.{name}={count}")
    for item in report["large_files"]:
        print(f"warning.large_file={item['path']} ({item['bytes']} bytes)")
    for warning in report["warnings"]:
        print(f"warning={warning}")
    for error in report["errors"]:
        print(f"error={error}")
    print("release_baseline=PASS" if report["ok"] else "release_baseline=FAIL")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="also fail when the Git worktree has tracked or untracked changes",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    report = audit_repository(PROJECT_ROOT, require_clean=args.require_clean)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

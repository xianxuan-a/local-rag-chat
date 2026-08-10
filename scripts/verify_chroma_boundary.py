"""Fail closed if production code exposes ChromaDB over HTTP."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PERSISTENT_CLIENT_RE = re.compile(r"chromadb\s*\.\s*PersistentClient\s*\(")
FORBIDDEN_PATTERNS = (
    (
        "remote Chroma client",
        re.compile(r"chromadb\s*\.\s*(?:Async)?HttpClient\s*\("),
    ),
    ("Chroma server module", re.compile(r"\bchromadb\s*\.\s*app\b")),
    (
        "Chroma server command",
        re.compile(r"(?:^|[\s\"'])(?:chroma|chromadb)\s+run(?:[\s\"']|$)", re.I),
    ),
)
COMPOSE_SERVICE_RE = re.compile(
    r"^  [^:\s]*chroma[^:\s]*:\s*(?:#.*)?$", re.I | re.M
)
CHROMA_IMAGE_RE = re.compile(
    r"\bimage:\s*[\"']?(?:chromadb/chroma|ghcr\.io/chroma-core/chroma)",
    re.I,
)


def production_paths(root: Path) -> list[Path]:
    paths = sorted((root / "app").rglob("*.py"))
    paths.extend(
        path
        for path in sorted((root / "scripts").glob("*.py"))
        if path.name != Path(__file__).name
    )
    paths.extend(
        path
        for path in (
            root / "run.py",
            root / "Dockerfile",
            root / "frontend" / "Dockerfile",
            root / "docker-compose.yml",
            root / "docker-compose.e2e.yml",
        )
        if path.is_file()
    )
    paths.extend(sorted((root / "ui").rglob("*.py")))
    return paths


def verify_boundary(root: Path, *, paths: list[Path] | None = None) -> list[str]:
    root = root.resolve()
    candidates = paths if paths is not None else production_paths(root)
    if not candidates:
        raise ValueError("no production files were found for Chroma boundary audit")

    errors: list[str] = []
    persistent_client_found = False
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        relative = path.resolve().relative_to(root).as_posix()
        if PERSISTENT_CLIENT_RE.search(text):
            persistent_client_found = True
        for description, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                errors.append(f"{relative}: forbidden {description}")
        if path.name.startswith("docker-compose"):
            if COMPOSE_SERVICE_RE.search(text):
                errors.append(f"{relative}: forbidden Chroma Compose service")
            if CHROMA_IMAGE_RE.search(text):
                errors.append(f"{relative}: forbidden Chroma server image")
        if path == root / "Dockerfile" and 'CMD ["python", "run.py"]' not in text:
            errors.append(
                f"{relative}: runtime command must remain the single application process"
            )

    if not persistent_client_found:
        errors.append("production code must construct chromadb.PersistentClient")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors = verify_boundary(PROJECT_ROOT)
    for error in errors:
        print(f"error={error}")
    print("chroma_boundary=PASS" if not errors else "chroma_boundary=FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

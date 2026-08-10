"""Fail-closed contracts for the local-only ChromaDB mitigation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_chroma_boundary import PROJECT_ROOT, verify_boundary


def _fixture(tmp_path: Path, content: str) -> list[Path]:
    fixture = tmp_path / "boundary.py"
    fixture.write_text(content, encoding="utf-8")
    return [fixture]


def test_production_chroma_boundary_is_local_persistent_only() -> None:
    assert verify_boundary(PROJECT_ROOT) == []


def test_boundary_accepts_only_persistent_client(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, "import chromadb\nchromadb.PersistentClient(path='data')\n")
    assert verify_boundary(tmp_path, paths=paths) == []


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (
            "import chromadb\nchromadb.PersistentClient(path='data')\n"
            "chromadb.HttpClient(host='example.com')\n",
            "remote Chroma client",
        ),
        (
            "import chromadb\nchromadb.PersistentClient(path='data')\n"
            "chromadb.AsyncHttpClient(host='example.com')\n",
            "remote Chroma client",
        ),
        (
            "import chromadb\nchromadb.PersistentClient(path='data')\n"
            "import chromadb.app\n",
            "server module",
        ),
        (
            "import chromadb\nchromadb.PersistentClient(path='data')\n"
            "command = 'chroma run --path data'\n",
            "server command",
        ),
    ),
)
def test_boundary_rejects_remote_clients_and_server_entrypoints(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    errors = verify_boundary(tmp_path, paths=_fixture(tmp_path, content))
    assert any(expected in error for error in errors)


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (
            "services:\n  chroma:\n    image: busybox\n"
            "# chromadb.PersistentClient(path='data')\n",
            "Compose service",
        ),
        (
            "services:\n  vector:\n    image: chromadb/chroma:1.5.9\n"
            "# chromadb.PersistentClient(path='data')\n",
            "server image",
        ),
    ),
)
def test_boundary_rejects_chroma_compose_server(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(content, encoding="utf-8")
    errors = verify_boundary(tmp_path, paths=[compose])
    assert any(expected in error for error in errors)

"""The rebuild utility remains a thin HTTP-only client."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_kb.py"
SPEC = importlib.util.spec_from_file_location("rebuild_kb_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
rebuild_kb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rebuild_kb)


def _response(status_code: int, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


def test_cli_posts_rebuild_and_preserves_server_json(monkeypatch, capsys) -> None:
    captured: dict = {}

    def post(url: str, timeout: float):
        captured.update(url=url, timeout=timeout)
        return _response(
            200,
            {
                "code": 0,
                "data": {"status": "SUCCESS", "switched": True},
            },
        )

    monkeypatch.setattr(rebuild_kb.requests, "post", post)

    exit_code = rebuild_kb.main(
        [
            "--knowledge-base-id",
            "00000000-0000-0000-0000-000000000001",
            "--api-base-url",
            "http://service.test/",
            "--timeout-seconds",
            "15",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "url": (
            "http://service.test/api/knowledge-bases/"
            "00000000-0000-0000-0000-000000000001/rebuild"
        ),
        "timeout": 15.0,
    }
    assert '"switched": true' in capsys.readouterr().out


def test_cli_exit_code_mapping(monkeypatch) -> None:
    monkeypatch.setattr(
        rebuild_kb.requests,
        "post",
        lambda *_args, **_kwargs: _response(
            409, {"code": 409, "message": "conflict"}
        ),
    )
    assert rebuild_kb.main(["--knowledge-base-id", "kb"]) == 1

    monkeypatch.setattr(
        rebuild_kb.requests,
        "post",
        lambda *_args, **_kwargs: _response(
            404, {"code": 404, "message": "missing"}
        ),
    )
    assert rebuild_kb.main(["--knowledge-base-id", "kb"]) == 2


def test_cli_source_does_not_import_database_or_chroma_services() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "chromadb",
        "PersistentClient",
        "VectorStoreService",
        "RetrievalService",
        "FileService",
        "KnowledgeBaseRebuildService",
    )
    assert all(name not in source for name in forbidden)

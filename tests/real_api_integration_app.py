"""Isolated Real API browser app with real parsing, Chroma, and local vectors."""

from __future__ import annotations

import os
from pathlib import Path
from http import HTTPStatus
import time
from typing import Any

from dashscope.api_entities.dashscope_response import GenerationResponse
from dashscope.common.error import RequestFailure
from pydantic import SecretStr

from app import main as app_main
from app.core.config import Settings
from app.database.migrations import upgrade_database
from app.models import JobType
from app.services import chat_model_service
from app.services.job_worker import JobHandler
from tests.fakes import FakeEmbedding


artifact_root_value = os.environ.get("NEXUS_REAL_API_ARTIFACT_ROOT", "").strip()
if not artifact_root_value:
    raise RuntimeError("NEXUS_REAL_API_ARTIFACT_ROOT must be set")

artifact_root = Path(artifact_root_value).resolve()
data_dir = artifact_root / "data"
settings = Settings(
    _env_file=None,
    ENVIRONMENT="production",
    AUTH_REQUIRED=True,
    ALLOW_REGISTRATION=False,
    LOG_DIR=artifact_root / "logs",
    DATA_DIR=data_dir,
    UPLOAD_DIR=data_dir / "uploads",
    CHROMA_DIR=data_dir / "chroma",
    METADATA_DIR=data_dir / "metadata",
    CHAT_HISTORY_DIR=data_dir / "chat_history",
    BACKUP_DIR=data_dir / "backups",
    EVALUATION_DIR=data_dir / "evaluations",
    DATABASE_URL=f"sqlite:///{(data_dir / 'metadata' / 'integration.db').as_posix()}",
    MAX_UPLOAD_SIZE_MB=1,
    JWT_SECRET="ddjtZY2DPGyFTdPiOuM7hp2-Ledc6QWj",
    METRICS_SCRAPE_TOKEN="P0MNWmaJ7qzFjJeZC3aHrwRRQDiwViTf",
    BACKUP_SIGNING_KEY="MZwKvVlYW5D2SBgB6jVbtWeLyVAawojm",
    BOOTSTRAP_SECRET="G5hczu_T4XWOLbPX2dYBzEDOQhP07qOW",
    CHAT_MODEL="isolated-deterministic-chat",
    DASHSCOPE_API_KEY=SecretStr("isolated-deterministic-key"),
)
settings.ensure_directories()
upgrade_database(settings.DATABASE_URL)


_default_handlers = app_main.build_default_job_handlers


def build_isolated_handlers(
    *,
    session_factory: Any,
    settings: Settings,
    runtime: Any,
) -> dict[JobType, JobHandler]:
    """Use deterministic local vectors while keeping the real processing path."""

    fake_embedding = FakeEmbedding()
    runtime.vector_store._embedding_factory = lambda _config: fake_embedding
    runtime.vector_store._embedding_cache.clear()
    return _default_handlers(
        session_factory=session_factory,
        settings=settings,
        runtime=runtime,
    )


app_main.build_default_job_handlers = build_isolated_handlers


def _chat_response(content: str) -> GenerationResponse:
    raw = GenerationResponse(
        status_code=HTTPStatus.OK,
        output={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    }
                }
            ]
        },
    )
    return GenerationResponse.from_api_response(raw)


def deterministic_chat(**kwargs: Any):
    """Network-free provider substitute over the real RAG and NDJSON paths."""

    messages = kwargs.get("messages")
    prompt = str(messages[-1].get("content", "")) if messages else ""
    if "模型失败" in prompt:
        raise RequestFailure(
            request_id="isolated-chat-failure",
            message="deterministic provider unavailable",
            name="ServiceUnavailable",
            http_code=503,
        )
    answer = (
        "越界回答 [K99]"
        if "越界引用" in prompt
        else "隔离环境中的确定性回答 [K1]"
    )
    if kwargs.get("stream") is not True:
        return _chat_response(answer)

    def generate():
        chunks = (
            ["这是一段", "可以停止的", "较慢回答 ", "[K1]"]
            if "可以停止" in prompt
            else ["隔离环境中的", "确定性回答 [K1]"]
        )
        for chunk in chunks:
            if "可以停止" in prompt:
                time.sleep(1.0)
            yield _chat_response(chunk)

    return generate()


chat_model_service.Generation.call = deterministic_chat
app = app_main.create_app(settings)


@app.get("/api/_test/error")
def deterministic_internal_error() -> None:
    """Expose a test-only 500 to verify proxy status preservation."""

    raise RuntimeError("deterministic integration failure")

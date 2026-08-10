"""Opt-in real DashScope smoke test; skipped by default."""

from __future__ import annotations

import os

import pytest

from app.services.embedding_service import (
    DashScopeEmbeddingAdapter,
    EmbeddingConfig,
)
from app.services.chat_model_service import (
    ChatRuntimeConfig,
    DashScopeChatClient,
)
from tests.conftest import make_test_settings


@pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_SMOKE") != "1"
    or not os.getenv("DASHSCOPE_API_KEY"),
    reason="requires RUN_DASHSCOPE_SMOKE=1 and DASHSCOPE_API_KEY",
)
def test_real_dashscope_embedding_batch_smoke(tmp_path) -> None:
    settings = make_test_settings(
        tmp_path,
        DASHSCOPE_API_KEY=os.environ["DASHSCOPE_API_KEY"],
        DASHSCOPE_BASE_URL=os.getenv("DASHSCOPE_BASE_URL"),
        EMBEDDING_MAX_RETRIES=1,
        EMBEDDING_BATCH_SIZE=2,
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
    )

    vectors = adapter.embed_documents(
        [
            "Synthetic RAG release smoke text one.",
            "Synthetic RAG release smoke text two.",
        ]
    )

    assert len(vectors) == 2
    assert all(len(vector) == 1024 for vector in vectors)


@pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_SMOKE") != "1"
    or not os.getenv("DASHSCOPE_API_KEY"),
    reason="requires RUN_DASHSCOPE_SMOKE=1 and DASHSCOPE_API_KEY",
)
def test_real_dashscope_single_chat_smoke() -> None:
    client = DashScopeChatClient(
        ChatRuntimeConfig(
            model=os.getenv("DASHSCOPE_STAGING_CHAT_MODEL", "qwen-turbo"),
            api_key=os.environ["DASHSCOPE_API_KEY"],
            base_url=os.getenv("DASHSCOPE_BASE_URL") or None,
            temperature=0.0,
            max_tokens=16,
            timeout_seconds=20,
        )
    )
    messages = [
        {
            "role": "system",
            "content": "This is an automated service health check.",
        },
        {
            "role": "user",
            "content": "Reply with one short English word meaning healthy.",
        }
    ]
    calls = 0

    def record_call() -> None:
        nonlocal calls
        calls += 1

    answer = client.generate(messages, before_generation_call=record_call)

    assert answer.strip()
    assert calls == 1

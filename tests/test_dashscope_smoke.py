"""Opt-in real DashScope smoke test; skipped by default."""

from __future__ import annotations

import os

import pytest

from app.services.embedding_service import (
    DashScopeEmbeddingAdapter,
    EmbeddingConfig,
)
from tests.conftest import make_test_settings


@pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_SMOKE") != "1"
    or not os.getenv("DASHSCOPE_API_KEY"),
    reason="requires RUN_DASHSCOPE_SMOKE=1 and DASHSCOPE_API_KEY",
)
def test_real_dashscope_embedding_smoke(tmp_path) -> None:
    settings = make_test_settings(
        tmp_path,
        DASHSCOPE_API_KEY=os.environ["DASHSCOPE_API_KEY"],
        DASHSCOPE_BASE_URL=os.getenv("DASHSCOPE_BASE_URL"),
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
    )

    vector = adapter.embed_query("RAG smoke test")

    assert len(vector) == 1024

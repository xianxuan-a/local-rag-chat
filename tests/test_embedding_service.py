"""DashScope request-contract and response-ordering tests without network."""

from __future__ import annotations

from types import SimpleNamespace
import math

import pytest

from app.core.exceptions import ModelServiceException, ValidationException
from app.services.embedding_service import (
    DashScopeEmbeddingAdapter,
    EmbeddingConfig,
)
from tests.conftest import make_test_settings


def _response(items: list[dict], status_code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        output={"embeddings": items},
    )


def _vector(index: int) -> list[float]:
    values = [0.0] * 1024
    values[index] = 2.0
    return values


def test_protocol_version_changes_vector_space_hash(test_settings) -> None:
    original = EmbeddingConfig.from_settings(test_settings)
    changed = EmbeddingConfig(
        provider=original.provider,
        model=original.model,
        dimension=original.dimension,
        normalization=original.normalization,
        distance_metric=original.distance_metric,
        protocol_version="dashscope-text-embedding-v2",
    )

    assert original.config_hash != changed.config_hash
    assert "api_key" not in original.canonical_dict()
    assert "base_url" not in original.canonical_dict()


def test_request_uses_audited_sdk_parameters_and_reorders_text_index(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_test_settings(
        tmp_path,
        DASHSCOPE_API_KEY="secret",
        DASHSCOPE_BASE_URL="https://example.invalid/api",
    )
    requests: list[dict] = []

    def call(**kwargs):
        requests.append(kwargs)
        return _response(
            [
                {"text_index": 1, "embedding": _vector(1)},
                {"text_index": 0, "embedding": _vector(0)},
            ]
        )

    monkeypatch.setattr(
        DashScopeEmbeddingAdapter,
        "_per_call_base_address_supported",
        True,
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
        call=call,
    )

    result = adapter.embed_documents(["first", "second"])

    assert result[0][0] == 1.0
    assert result[1][1] == 1.0
    assert set(requests[0]) == {
        "model",
        "input",
        "text_type",
        "dimension",
        "output_type",
        "api_key",
        "request_timeout",
        "base_address",
    }
    assert requests[0]["text_type"] == "document"
    assert requests[0]["dimension"] == 1024
    assert requests[0]["output_type"] == "dense"
    assert requests[0]["request_timeout"] == 30
    assert "timeout" not in requests[0]
    assert "workspace" not in requests[0]
    assert "stream" not in requests[0]


@pytest.mark.parametrize(
    "items",
    [
        [
            {"text_index": 0, "embedding": _vector(0)},
            {"text_index": 0, "embedding": _vector(1)},
        ],
        [
            {"text_index": 0, "embedding": _vector(0)},
            {"text_index": 2, "embedding": _vector(1)},
        ],
        [
            {"text_index": True, "embedding": _vector(0)},
            {"text_index": 1, "embedding": _vector(1)},
        ],
    ],
)
def test_invalid_text_index_fails_entire_batch(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    items: list[dict],
) -> None:
    settings = make_test_settings(tmp_path, DASHSCOPE_API_KEY="secret")
    monkeypatch.setattr(
        DashScopeEmbeddingAdapter,
        "_per_call_base_address_supported",
        True,
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
        call=lambda **_: _response(items),
    )

    with pytest.raises(ModelServiceException):
        adapter.embed_documents(["first", "second"])


def test_retryable_status_uses_three_total_attempts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_test_settings(
        tmp_path,
        DASHSCOPE_API_KEY="secret",
        EMBEDDING_MAX_RETRIES=3,
    )
    calls = 0
    sleeps: list[float] = []

    def call(**_):
        nonlocal calls
        calls += 1
        if calls < 3:
            return _response([], status_code=429)
        return _response([{"text_index": 0, "embedding": _vector(0)}])

    monkeypatch.setattr(
        DashScopeEmbeddingAdapter,
        "_per_call_base_address_supported",
        True,
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
        call=call,
        sleep=sleeps.append,
    )

    assert adapter.embed_query("query")[0] == 1.0
    assert calls == 3
    assert sleeps == [1, 2]


def test_bad_request_is_not_retried(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_test_settings(tmp_path, DASHSCOPE_API_KEY="secret")
    calls = 0

    def call(**_):
        nonlocal calls
        calls += 1
        return _response([], status_code=400)

    monkeypatch.setattr(
        DashScopeEmbeddingAdapter,
        "_per_call_base_address_supported",
        True,
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
        call=call,
    )

    with pytest.raises(ModelServiceException):
        adapter.embed_query("query")
    assert calls == 1


def test_unknown_request_argument_is_rejected() -> None:
    with pytest.raises(ValidationException):
        DashScopeEmbeddingAdapter._validate_request_keys(
            {
                "model": "text-embedding-v4",
                "input": "query",
                "text_type": "query",
                "dimension": 1024,
                "output_type": "dense",
                "api_key": "secret",
                "request_timeout": 30,
                "workspace": "not-allowed",
            }
        )


def test_installed_sdk_supports_per_call_base_address() -> None:
    assert DashScopeEmbeddingAdapter._detect_per_call_base_address() is True


@pytest.mark.parametrize(
    "value",
    [
        [0.0] * 1024,
        [math.nan] + [0.0] * 1023,
        [math.inf] + [0.0] * 1023,
        [1.0] * 1023,
    ],
)
def test_invalid_vectors_are_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    value: list[float],
) -> None:
    settings = make_test_settings(tmp_path, DASHSCOPE_API_KEY="secret")
    monkeypatch.setattr(
        DashScopeEmbeddingAdapter,
        "_per_call_base_address_supported",
        True,
    )
    adapter = DashScopeEmbeddingAdapter(
        settings,
        EmbeddingConfig.from_settings(settings),
        call=lambda **_: None,
    )

    with pytest.raises(ModelServiceException):
        adapter._normalize_vector(value)

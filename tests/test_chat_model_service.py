"""DashScope chat adapter tests without network access."""

from __future__ import annotations

from http import HTTPStatus

import pytest

from dashscope.api_entities.dashscope_response import GenerationResponse
from dashscope.common.error import AuthenticationError, RequestFailure, TimeoutException

from app.services.chat_model_service import (
    ChatAuthenticationError,
    ChatContextLengthError,
    ChatInvalidRequestError,
    ChatMalformedResponseError,
    ChatRuntimeConfig,
    ChatTimeoutError,
    ChatTransientServiceError,
    DashScopeChatClient,
)


def _config(**overrides) -> ChatRuntimeConfig:
    values = {
        "model": "test-model",
        "api_key": "test-key",
        "base_url": "https://example.invalid/api",
        "temperature": 0.1,
        "max_tokens": 128,
        "timeout_seconds": 12.0,
    }
    values.update(overrides)
    return ChatRuntimeConfig(**values)


def _messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]


def _success(content: str = "ok") -> GenerationResponse:
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


def _error(status: int, code: str, message: str) -> GenerationResponse:
    return GenerationResponse(
        status_code=status,
        code=code,
        message=message,
        request_id="request-1",
    )


def test_generate_passes_audited_parameters_and_calls_once(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    before_calls = 0

    def fake_call(**kwargs):
        calls.append(kwargs)
        return _success("answer")

    def before():
        nonlocal before_calls
        before_calls += 1

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_call,
    )
    answer = DashScopeChatClient(_config()).generate(
        _messages(),
        before_generation_call=before,
    )

    assert answer == "answer"
    assert before_calls == 1
    assert len(calls) == 1
    assert calls[0] == {
        "model": "test-model",
        "messages": _messages(),
        "temperature": 0.1,
        "max_tokens": 128,
        "request_timeout": 12.0,
        "result_format": "message",
        "stream": False,
        "api_key": "test-key",
        "base_address": "https://example.invalid/api",
    }


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (_error(401, "InvalidApiKey", "invalid"), ChatAuthenticationError),
        (_error(429, "Throttling", "limited"), ChatTransientServiceError),
        (_error(500, "InternalError", "failed"), ChatTransientServiceError),
        (
            _error(
                400,
                "InvalidParameter",
                "maximum context length exceeded",
            ),
            ChatContextLengthError,
        ),
        (_error(400, "InvalidParameter", "bad temperature"), ChatInvalidRequestError),
    ],
)
def test_provider_status_and_codes_become_typed_errors(
    monkeypatch,
    response,
    error_type,
) -> None:
    calls = 0

    def fake_call(**_kwargs):
        nonlocal calls
        calls += 1
        return response

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_call,
    )

    with pytest.raises(error_type):
        DashScopeChatClient(_config()).generate(
            _messages(),
            before_generation_call=lambda: None,
        )

    assert calls == 1


def test_sdk_timeout_becomes_typed_error_without_internal_retry(
    monkeypatch,
) -> None:
    calls = 0

    def fake_call(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutException("timeout")

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_call,
    )

    with pytest.raises(ChatTimeoutError):
        DashScopeChatClient(_config()).generate(
            _messages(),
            before_generation_call=lambda: None,
        )

    assert calls == 1


@pytest.mark.parametrize(
    ("sdk_error", "error_type"),
    [
        (AuthenticationError("bad key"), ChatAuthenticationError),
        (
            RequestFailure(
                request_id="request-2",
                message="limited",
                name="Throttling",
                http_code=429,
            ),
            ChatTransientServiceError,
        ),
    ],
)
def test_sdk_exceptions_become_typed_errors_without_retry(
    monkeypatch,
    sdk_error,
    error_type,
) -> None:
    calls = 0

    def fake_call(**_kwargs):
        nonlocal calls
        calls += 1
        raise sdk_error

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_call,
    )

    with pytest.raises(error_type):
        DashScopeChatClient(_config()).generate(
            _messages(),
            before_generation_call=lambda: None,
        )

    assert calls == 1


def test_incompatible_success_response_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: object(),
    )

    with pytest.raises(ChatMalformedResponseError):
        DashScopeChatClient(_config()).generate(
            _messages(),
            before_generation_call=lambda: None,
        )


def test_local_message_validation_happens_before_attempt_callback() -> None:
    before_calls = 0

    def before():
        nonlocal before_calls
        before_calls += 1

    with pytest.raises(ChatInvalidRequestError):
        DashScopeChatClient(_config()).generate(
            [{"role": "user", "content": "only one"}],
            before_generation_call=before,
        )

    assert before_calls == 0


def test_stream_generate_uses_incremental_provider_output(
    monkeypatch,
) -> None:
    calls = []
    before_calls = 0

    def fake_call(**kwargs):
        calls.append(kwargs)
        return iter([_success("一"), _success(" 二")])

    def before():
        nonlocal before_calls
        before_calls += 1

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        fake_call,
    )
    deltas = list(
        DashScopeChatClient(_config()).stream_generate(
            _messages(),
            before_generation_call=before,
        )
    )

    assert deltas == ["一", " 二"]
    assert before_calls == 1
    assert calls[0]["stream"] is True
    assert calls[0]["incremental_output"] is True


def test_closing_stream_closes_provider_iterator(monkeypatch) -> None:
    class ProviderIterator:
        def __init__(self) -> None:
            self.closed = False
            self.responses = iter([_success("first"), _success("second")])

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.responses)

        def close(self) -> None:
            self.closed = True

    provider = ProviderIterator()
    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: provider,
    )
    stream = DashScopeChatClient(_config()).stream_generate(
        _messages(),
        before_generation_call=lambda: None,
    )

    assert next(stream) == "first"
    stream.close()

    assert provider.closed is True

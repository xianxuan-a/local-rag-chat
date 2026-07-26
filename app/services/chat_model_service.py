"""Lazy, single-call DashScope chat adapter with provider error isolation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http import HTTPStatus
import math
from typing import Any, Protocol

from dashscope import Generation
from dashscope.api_entities.dashscope_response import (
    GenerationOutput,
    GenerationResponse,
)
from dashscope.common.error import (
    AssistantError,
    AuthenticationError,
    DashScopeException,
    InvalidInput,
    InvalidModel,
    InvalidParameter,
    ModelRequired,
    RequestFailure,
    ServiceUnavailableError,
    TimeoutException,
    UnsupportedModel,
)
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout


@dataclass(frozen=True, slots=True)
class ChatRuntimeConfig:
    """Validated non-persistent parameters for one chat client."""

    model: str
    api_key: str
    base_url: str | None
    temperature: float
    max_tokens: int
    timeout_seconds: float


class ChatClientError(Exception):
    """Base error that hides provider-specific exception details from RAG."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.provider_code = provider_code
        self.request_id = request_id
        super().__init__(message)


class ChatAuthenticationError(ChatClientError):
    pass


class ChatInvalidRequestError(ChatClientError):
    pass


class ChatContextLengthError(ChatClientError):
    pass


class ChatTimeoutError(ChatClientError):
    pass


class ChatTransientServiceError(ChatClientError):
    pass


class ChatMalformedResponseError(ChatClientError):
    pass


class ChatClientInitializationError(ChatClientError):
    pass


class ChatAttemptLimitError(ChatClientError):
    pass


class ChatClient(Protocol):
    """One logical chat call; implementations must never retry internally."""

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        before_generation_call: Callable[[], None],
    ) -> str:
        ...

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        *,
        before_generation_call: Callable[[], None],
    ) -> Iterator[str]:
        ...


ChatClientFactory = Callable[[ChatRuntimeConfig], ChatClient]


_CONTEXT_ERROR_CODES = {
    "badrequest",
    "invalidinput",
    "invalidparameter",
    "inputdatarequired",
}
_CONTEXT_ERROR_MARKERS = (
    "context length",
    "context_length",
    "input length",
    "input_length",
    "maximum context",
    "max context",
    "token limit",
    "too many tokens",
    "too long",
)


class DashScopeChatClient:
    """Perform exactly one DashScope Generation request per ``generate`` call."""

    def __init__(self, config: ChatRuntimeConfig) -> None:
        self.config = config
        self._validate_config(config)

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        before_generation_call: Callable[[], None],
    ) -> str:
        self._validate_messages(messages)
        kwargs = self._request_kwargs(messages, stream=False)
        before_generation_call()
        response = self._call_generation(kwargs)
        if not isinstance(response, GenerationResponse):
            raise ChatMalformedResponseError("聊天模型返回了不兼容的响应")
        self._validate_response(response)
        return self._extract_content(response).strip()

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        *,
        before_generation_call: Callable[[], None],
    ) -> Iterator[str]:
        """Yield only genuine incremental content returned by DashScope."""

        self._validate_messages(messages)
        kwargs = self._request_kwargs(messages, stream=True)
        before_generation_call()
        responses = self._call_generation(kwargs)
        if isinstance(responses, GenerationResponse):
            raise ChatMalformedResponseError("聊天模型未返回流式响应")
        try:
            iterator = iter(responses)
        except TypeError as exc:
            raise ChatMalformedResponseError("聊天模型返回了不兼容的流") from exc

        try:
            while True:
                try:
                    response = next(iterator)
                except StopIteration:
                    break
                except Exception as exc:
                    raise self._translate_sdk_exception(exc) from exc
                if not isinstance(response, GenerationResponse):
                    raise ChatMalformedResponseError("聊天模型流包含无效响应")
                self._validate_response(response)
                content = self._extract_content(response, allow_empty=True)
                if content:
                    yield content
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

    def _request_kwargs(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "request_timeout": self.config.timeout_seconds,
            "result_format": "message",
            "stream": stream,
            "api_key": self.config.api_key,
        }
        if stream:
            kwargs["incremental_output"] = True
        if self.config.base_url is not None:
            kwargs["base_address"] = self.config.base_url
        return kwargs

    def _call_generation(self, kwargs: dict[str, Any]) -> Any:
        try:
            return Generation.call(**kwargs)
        except Exception as exc:
            raise self._translate_sdk_exception(exc) from exc

    @classmethod
    def _validate_response(cls, response: GenerationResponse) -> None:
        status_code = cls._coerce_status_code(response.status_code)
        if status_code != HTTPStatus.OK:
            raise cls._from_provider_error(
                status_code=status_code,
                provider_code=response.code,
                provider_message=response.message,
                request_id=response.request_id,
            )

    @staticmethod
    def _validate_config(config: ChatRuntimeConfig) -> None:
        if not isinstance(config.model, str) or not config.model.strip():
            raise ChatClientInitializationError("聊天模型名称未配置")
        if not isinstance(config.api_key, str) or not config.api_key:
            raise ChatClientInitializationError("聊天模型 API Key 未配置")
        if (
            isinstance(config.temperature, bool)
            or not isinstance(config.temperature, (int, float))
            or not math.isfinite(float(config.temperature))
            or not 0 <= float(config.temperature) < 2
        ):
            raise ChatClientInitializationError("聊天模型 temperature 配置无效")
        if (
            isinstance(config.max_tokens, bool)
            or not isinstance(config.max_tokens, int)
            or config.max_tokens < 1
        ):
            raise ChatClientInitializationError("聊天模型 max_tokens 配置无效")
        if (
            isinstance(config.timeout_seconds, bool)
            or not isinstance(config.timeout_seconds, (int, float))
            or not math.isfinite(float(config.timeout_seconds))
            or config.timeout_seconds <= 0
        ):
            raise ChatClientInitializationError("聊天模型超时配置无效")
        if config.base_url is not None and not config.base_url:
            raise ChatClientInitializationError("聊天模型服务地址配置无效")

    @staticmethod
    def _validate_messages(messages: list[dict[str, str]]) -> None:
        if not isinstance(messages, list) or len(messages) != 2:
            raise ChatInvalidRequestError("聊天消息结构无效")
        if [message.get("role") for message in messages] != ["system", "user"]:
            raise ChatInvalidRequestError("聊天消息角色无效")
        for message in messages:
            if set(message) != {"role", "content"}:
                raise ChatInvalidRequestError("聊天消息包含未审核字段")
            if not isinstance(message["content"], str) or not message["content"]:
                raise ChatInvalidRequestError("聊天消息正文不能为空")

    @staticmethod
    def _extract_content(
        response: GenerationResponse,
        *,
        allow_empty: bool = False,
    ) -> str:
        output = response.output
        if not isinstance(output, GenerationOutput):
            raise ChatMalformedResponseError("聊天模型响应缺少 output")
        choices = output.choices
        if not isinstance(choices, list) or not choices:
            raise ChatMalformedResponseError("聊天模型响应缺少 choices")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            raise ChatMalformedResponseError("聊天模型响应缺少回答正文")
        if not allow_empty and not content.strip():
            raise ChatMalformedResponseError("聊天模型返回了空回答")
        return content

    @classmethod
    def _translate_sdk_exception(cls, exc: Exception) -> ChatClientError:
        if isinstance(exc, ChatClientError):
            return exc
        if isinstance(exc, (TimeoutException, RequestsTimeout)):
            return ChatTimeoutError("聊天模型请求超时")
        if isinstance(exc, (ServiceUnavailableError, RequestsConnectionError)):
            return ChatTransientServiceError("聊天模型服务暂时不可用")
        if isinstance(exc, AuthenticationError):
            return ChatAuthenticationError("聊天模型认证失败")
        if isinstance(exc, (InvalidModel, UnsupportedModel, ModelRequired)):
            return ChatInvalidRequestError("聊天模型配置无效")
        if isinstance(exc, (InvalidParameter, InvalidInput)):
            if cls._is_context_length_error(type(exc).__name__, str(exc)):
                return ChatContextLengthError("聊天模型上下文超过限制")
            return ChatInvalidRequestError("聊天模型请求参数无效")
        if isinstance(exc, RequestFailure):
            return cls._from_provider_error(
                status_code=exc.http_code,
                provider_code=exc.name,
                provider_message=exc.message,
                request_id=exc.request_id,
            )
        if isinstance(exc, AssistantError):
            return cls._from_provider_error(
                status_code=None,
                provider_code=exc.code,
                provider_message=exc.message,
                request_id=exc.request_id,
            )
        if isinstance(exc, DashScopeException):
            return ChatInvalidRequestError("聊天模型请求失败")
        return ChatMalformedResponseError("聊天模型调用异常")

    @classmethod
    def _from_provider_error(
        cls,
        *,
        status_code: object,
        provider_code: object,
        provider_message: object,
        request_id: object,
    ) -> ChatClientError:
        status = cls._coerce_status_code(status_code)
        code = str(provider_code) if provider_code else None
        message = str(provider_message) if provider_message else ""
        request = str(request_id) if request_id else None
        details = {
            "status_code": status,
            "provider_code": code,
            "request_id": request,
        }
        if status in {401, 403}:
            return ChatAuthenticationError("聊天模型认证或权限校验失败", **details)
        if status == 429:
            return ChatTransientServiceError("聊天模型服务请求受限", **details)
        if status is not None and status >= 500:
            return ChatTransientServiceError("聊天模型服务暂时不可用", **details)
        if cls._is_context_length_error(code, message):
            return ChatContextLengthError("聊天模型上下文超过限制", **details)
        return ChatInvalidRequestError("聊天模型请求被拒绝", **details)

    @staticmethod
    def _coerce_status_code(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_context_length_error(code: object, message: object) -> bool:
        normalized_code = str(code or "").replace("_", "").lower()
        normalized_message = str(message or "").lower()
        return (
            normalized_code in _CONTEXT_ERROR_CODES
            and any(marker in normalized_message for marker in _CONTEXT_ERROR_MARKERS)
        )


def create_dashscope_chat_client(config: ChatRuntimeConfig) -> ChatClient:
    """Default lazy factory used by ``RagService``."""

    return DashScopeChatClient(config)

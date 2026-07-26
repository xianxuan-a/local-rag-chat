"""DashScope embeddings with explicit request and response validation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import inspect
import json
import math
import threading
import time
from typing import Any, Callable

from langchain_core.embeddings import Embeddings
from requests import exceptions as requests_exceptions

from app.core.config import Settings
from app.core.exceptions import ModelServiceException, ValidationException


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """Fields that define one compatible vector space."""

    provider: str
    model: str
    dimension: int
    normalization: str
    distance_metric: str
    protocol_version: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "EmbeddingConfig":
        return cls(
            provider=settings.EMBEDDING_PROVIDER,
            model=settings.EMBEDDING_MODEL,
            dimension=settings.EMBEDDING_DIMENSION,
            normalization=settings.EMBEDDING_NORMALIZATION,
            distance_metric=settings.VECTOR_DISTANCE_METRIC,
            protocol_version=settings.EMBEDDING_PROTOCOL_VERSION,
        )

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> "EmbeddingConfig":
        try:
            dimension = metadata["embedding_dimension"]
            if isinstance(dimension, bool):
                raise TypeError
            return cls(
                provider=str(metadata["embedding_provider"]),
                model=str(metadata["embedding_model"]),
                dimension=int(dimension),
                normalization=str(metadata["embedding_normalization"]),
                distance_metric=str(metadata["distance_metric"]),
                protocol_version=str(metadata["embedding_protocol_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationException("Collection Embedding metadata 不完整") from exc

    def canonical_dict(self) -> dict[str, str | int]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
            "normalization": self.normalization,
            "distance_metric": self.distance_metric,
            "protocol_version": self.protocol_version,
        }

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def validate_supported(self) -> None:
        if self.provider != "dashscope":
            raise ModelServiceException(
                f"不支持的 Embedding provider：{self.provider}"
            )
        if self.model != "text-embedding-v4":
            raise ModelServiceException("当前仅支持 text-embedding-v4")
        if self.dimension != 1024:
            raise ModelServiceException("当前向量协议固定使用 1024 维")
        if self.normalization != "l2":
            raise ModelServiceException("当前仅支持 l2 向量归一化")
        if self.distance_metric != "cosine":
            raise ModelServiceException("当前仅支持 cosine 距离空间")
        if self.protocol_version != "dashscope-text-embedding-v1":
            raise ModelServiceException("不支持的 Embedding 协议版本")


class DashScopeEmbeddingAdapter(Embeddings):
    """Precompute dense vectors without exposing provider state to Chroma."""

    _endpoint_lock = threading.Lock()
    _global_base_url: str | None = None
    _per_call_base_address_supported: bool | None = None

    def __init__(
        self,
        settings: Settings,
        config: EmbeddingConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        call: Callable[..., Any] | None = None,
    ) -> None:
        config.validate_supported()
        self.settings = settings
        self.config = config
        self._sleep = sleep
        self._call_override = call
        self._base_url = settings.DASHSCOPE_BASE_URL
        self._api_key = settings.DASHSCOPE_API_KEY.get_secret_value()
        if not self._api_key:
            raise ModelServiceException("DASHSCOPE_API_KEY 未配置")
        self._use_per_call_base_address = self._resolve_endpoint_strategy()

    @property
    def runtime_cache_key(self) -> str:
        key_fingerprint = sha256(self._api_key.encode("utf-8")).hexdigest()
        payload = json.dumps(
            {
                "config_hash": self.config.config_hash,
                "base_url": self._base_url,
                "timeout": self.settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS,
                "retries": self.settings.EMBEDDING_MAX_RETRIES,
                "api_key_fingerprint": key_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or not texts:
            raise ValidationException("Embedding 文档列表不能为空")
        results: list[list[float]] = []
        batch_size = self.settings.EMBEDDING_BATCH_SIZE
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            request = self._build_request(batch, text_type="document")
            results.extend(self._request_batch(request, len(batch)))
        return results

    def embed_query(self, text: str) -> list[float]:
        request = self._build_request(text, text_type="query")
        return self._request_batch(request, 1)[0]

    def _build_request(
        self,
        input_value: str | list[str],
        *,
        text_type: str,
    ) -> dict[str, Any]:
        if text_type not in {"document", "query"}:
            raise ValidationException("DashScope text_type 无效")
        if text_type == "query":
            if not isinstance(input_value, str) or not input_value.strip():
                raise ValidationException("查询文本不能为空")
        else:
            if not isinstance(input_value, list) or not input_value:
                raise ValidationException("文档批次不能为空")
            if len(input_value) > self.settings.EMBEDDING_BATCH_SIZE:
                raise ValidationException("文档批次超过配置上限")
            if any(not isinstance(item, str) or not item.strip() for item in input_value):
                raise ValidationException("文档批次不能包含空文本")

        timeout = self.settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValidationException("DashScope 请求超时必须是有限正数")
        if self.config.dimension != self.settings.EMBEDDING_DIMENSION:
            raise ValidationException("Embedding 维度与运行配置不一致")

        if not isinstance(self.config.model, str) or not self.config.model.strip():
            raise ValidationException("DashScope model 不能为空")
        if not self._api_key:
            raise ValidationException("DashScope api_key 不能为空")

        request: dict[str, Any] = {
            "model": self.config.model,
            "input": input_value,
            "text_type": text_type,
            "dimension": self.config.dimension,
            "output_type": "dense",
            "api_key": self._api_key,
            # dashscope==1.26.4 consumes request_timeout in
            # api_request_factory._get_protocol_params.
            "request_timeout": timeout,
        }
        if self._base_url and self._use_per_call_base_address:
            request["base_address"] = self._base_url
        self._validate_request_keys(request)
        return request

    @staticmethod
    def _validate_request_keys(request: dict[str, Any]) -> None:
        allowed = {
            "model",
            "input",
            "text_type",
            "dimension",
            "output_type",
            "api_key",
            "request_timeout",
            "base_address",
        }
        unknown = set(request) - allowed
        if unknown:
            raise ValidationException(
                "DashScope 请求包含未审核参数：" + ", ".join(sorted(unknown))
            )
        if request["output_type"] != "dense":
            raise ValidationException("DashScope output_type 必须为 dense")
        if (
            isinstance(request["dimension"], bool)
            or request["dimension"] != 1024
        ):
            raise ValidationException("DashScope dimension 必须为 1024")
        if request["text_type"] not in {"document", "query"}:
            raise ValidationException("DashScope text_type 无效")

    def _request_batch(
        self,
        request: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.EMBEDDING_MAX_RETRIES + 1):
            try:
                response = self._provider_call(**request)
                status_code = int(getattr(response, "status_code", 0))
                if status_code == 200:
                    return self._parse_response(response, expected_count)
                if status_code in {400, 401, 403}:
                    raise ModelServiceException(
                        f"DashScope 请求被拒绝（HTTP {status_code}）"
                    )
                if status_code == 429 or 500 <= status_code <= 599:
                    raise _RetryableProviderError(status_code)
                raise ModelServiceException(
                    f"DashScope 返回异常状态（HTTP {status_code or 'unknown'}）"
                )
            except ModelServiceException:
                raise
            except (
                requests_exceptions.Timeout,
                requests_exceptions.ConnectionError,
                requests_exceptions.HTTPError,
                TimeoutError,
                ConnectionError,
                _RetryableProviderError,
            ) as exc:
                last_error = exc
                if attempt >= self.settings.EMBEDDING_MAX_RETRIES:
                    break
                self._sleep(min(2 ** (attempt - 1), 4))
            except Exception as exc:
                raise ModelServiceException("DashScope Embedding 调用失败") from exc
        raise ModelServiceException("DashScope Embedding 重试后仍失败") from last_error

    def _provider_call(self, **request: Any) -> Any:
        if self._call_override is not None:
            return self._call_override(**request)
        from dashscope import TextEmbedding

        return TextEmbedding.call(**request)

    def _parse_response(
        self,
        response: Any,
        expected_count: int,
    ) -> list[list[float]]:
        output = getattr(response, "output", None)
        items = output.get("embeddings") if isinstance(output, dict) else None
        if not isinstance(items, list) or len(items) != expected_count:
            raise ModelServiceException("DashScope 返回向量数量不匹配")

        indexed: dict[int, list[float]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ModelServiceException("DashScope 返回向量结构无效")
            text_index = item.get("text_index")
            if isinstance(text_index, bool) or not isinstance(text_index, int):
                raise ModelServiceException("DashScope text_index 必须为整数")
            if text_index < 0 or text_index >= expected_count:
                raise ModelServiceException("DashScope text_index 越界")
            if text_index in indexed:
                raise ModelServiceException("DashScope text_index 重复")
            indexed[text_index] = self._normalize_vector(item.get("embedding"))

        if set(indexed) != set(range(expected_count)):
            raise ModelServiceException("DashScope text_index 集合不完整")
        return [indexed[index] for index in range(expected_count)]

    def _normalize_vector(self, value: Any) -> list[float]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ModelServiceException("DashScope 返回空向量")
        if len(value) != self.config.dimension:
            raise ModelServiceException("DashScope 返回向量维度不匹配")
        vector: list[float] = []
        for item in value:
            if isinstance(item, bool):
                raise ModelServiceException("DashScope 向量包含非法数值")
            try:
                number = float(item)
            except (TypeError, ValueError) as exc:
                raise ModelServiceException("DashScope 向量包含非法数值") from exc
            if not math.isfinite(number):
                raise ModelServiceException("DashScope 向量包含非有限值")
            vector.append(number)
        norm = math.sqrt(sum(number * number for number in vector))
        if norm == 0:
            raise ModelServiceException("DashScope 返回零向量")
        return [number / norm for number in vector]

    def _resolve_endpoint_strategy(self) -> bool:
        if not self._base_url:
            return True
        with self._endpoint_lock:
            supported = self.__class__._per_call_base_address_supported
            if supported is None:
                supported = self._detect_per_call_base_address()
                self.__class__._per_call_base_address_supported = supported
            if supported:
                return True

            existing = self.__class__._global_base_url
            if existing is not None and existing != self._base_url:
                raise ModelServiceException(
                    "当前进程的 DashScope Base URL 已固定，不能动态切换"
                )
            import dashscope

            dashscope.base_http_api_url = self._base_url
            self.__class__._global_base_url = self._base_url
            return False

    @staticmethod
    def _detect_per_call_base_address() -> bool:
        try:
            from dashscope import TextEmbedding
            from dashscope.client.base_api import BaseApi

            signature = inspect.signature(TextEmbedding.call)
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            base_signature = inspect.signature(BaseApi.call)
            base_accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in base_signature.parameters.values()
            )
            build_request = BaseApi.call.__globals__.get("_build_api_request")
            protocol_parser = (
                build_request.__globals__.get("_get_protocol_params")
                if build_request is not None
                else None
            )
            parser_source = (
                inspect.getsource(protocol_parser)
                if protocol_parser is not None
                else ""
            )
            return (
                accepts_kwargs
                and base_accepts_kwargs
                and 'kwargs.pop("base_address"' in parser_source
            )
        except (ImportError, OSError, TypeError, ValueError):
            return False


class _RetryableProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"retryable provider status {status_code}")

"""FastAPI 的轻量 HTTP 客户端。

该模块是 Streamlit 与后端交互的唯一入口；它不依赖数据库、Repository
或任何 RAG 基础设施。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ApiClientError(RuntimeError):
    """可安全展示给前端用户的 API 调用错误。"""


class UiSettings(BaseSettings):
    """只包含 Streamlit HTTP 客户端所需的配置。"""

    API_BASE_URL: str = "http://localhost:8000"
    API_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0, le=60)

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("API_BASE_URL")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API_BASE_URL 必须是有效的 HTTP(S) 地址")
        return normalized


class ApiClient:
    """封装 Local RAG Chat 的统一响应协议。"""

    def __init__(self, base_url: str, timeout_seconds: float = 3.0) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("API 地址不能为空")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("API 请求超时必须大于 0")
        self.base_url = normalized_url
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method=method,
                url=url,
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ApiClientError(
                f"后端请求超时（{self.timeout_seconds:g} 秒）"
            ) from exc
        except requests.ConnectionError as exc:
            raise ApiClientError(f"无法连接后端：{self.base_url}") from exc
        except requests.RequestException as exc:
            raise ApiClientError(f"后端请求失败：{exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiClientError(
                f"后端返回了无法解析的响应（HTTP {response.status_code}）"
            ) from exc

        if not isinstance(payload, dict):
            raise ApiClientError("后端响应格式错误：应为 JSON 对象")

        message = str(payload.get("message") or "请求失败")
        code = payload.get("code")
        if not response.ok:
            raise ApiClientError(f"{message}（HTTP {response.status_code}）")
        if code != 0:
            raise ApiClientError(f"{message}（业务码 {code}）")
        if "data" not in payload:
            raise ApiClientError("后端响应格式错误：缺少 data 字段")
        return payload["data"]

    def health(self) -> dict[str, Any]:
        data = self._request("GET", "/health")
        if not isinstance(data, dict):
            raise ApiClientError("健康检查响应格式错误")
        return data

    def list_knowledge_bases(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/knowledge-bases")
        if not isinstance(data, list):
            raise ApiClientError("知识库列表响应格式错误")
        return [item for item in data if isinstance(item, dict)]

    def create_knowledge_base(
        self, name: str, description: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if description:
            body["description"] = description
        data = self._request("POST", "/api/knowledge-bases", json=body)
        if not isinstance(data, dict):
            raise ApiClientError("创建知识库响应格式错误")
        return data

    def upload_file(
        self,
        knowledge_base_id: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        files = {
            "file": (
                filename,
                content,
                content_type or "application/octet-stream",
            )
        }
        data = self._request(
            "POST",
            "/api/files/upload",
            data={"knowledge_base_id": knowledge_base_id},
            files=files,
        )
        if not isinstance(data, dict):
            raise ApiClientError("上传文件响应格式错误")
        return data

    def chat(
        self,
        knowledge_base_id: str,
        question: str,
        *,
        session_id: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/chat",
            json={
                "knowledge_base_id": knowledge_base_id,
                "session_id": session_id,
                "question": question,
                "top_k": top_k,
            },
        )
        if not isinstance(data, dict):
            raise ApiClientError("问答响应格式错误")
        return data


def api_client_from_env() -> ApiClient:
    """从环境变量或项目根目录的 ``.env`` 创建客户端。"""

    try:
        settings = UiSettings()
    except ValidationError as exc:
        raise ApiClientError("前端 API 配置无效，请检查 .env") from exc
    return ApiClient(
        base_url=settings.API_BASE_URL,
        timeout_seconds=settings.API_TIMEOUT_SECONDS,
    )

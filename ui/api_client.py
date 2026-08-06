"""FastAPI 的轻量 HTTP 客户端。

该模块是 Streamlit 与后端交互的唯一入口；它不依赖数据库、Repository
或任何 RAG 基础设施。
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import math
import time
from pathlib import Path
from typing import Any, Callable
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
    API_STREAM_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0, le=3600)

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

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 3.0,
        stream_timeout_seconds: float = 120.0,
        access_token: str | None = None,
        on_auth_failure: Callable[[], None] | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("API 地址不能为空")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("API 请求超时必须大于 0")
        if (
            not math.isfinite(stream_timeout_seconds)
            or stream_timeout_seconds <= 0
        ):
            raise ValueError("流式 API 请求超时必须大于 0")
        self.base_url = normalized_url
        self.timeout_seconds = timeout_seconds
        self.stream_timeout_seconds = stream_timeout_seconds
        self.access_token = access_token
        self.on_auth_failure = on_auth_failure

    def set_access_token(self, token: str | None) -> None:
        self.access_token = token

    def set_auth_failure_handler(
        self, handler: Callable[[], None] | None
    ) -> None:
        self.on_auth_failure = handler

    def _authenticated_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if not self.access_token:
            return kwargs
        updated = dict(kwargs)
        headers = dict(updated.pop("headers", {}) or {})
        headers.setdefault("Authorization", f"Bearer {self.access_token}")
        updated["headers"] = headers
        return updated

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        request_timeout = kwargs.pop("_timeout_seconds", self.timeout_seconds)
        kwargs = self._authenticated_kwargs(kwargs)
        try:
            response = requests.request(
                method=method,
                url=url,
                timeout=request_timeout,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ApiClientError(
                f"后端请求超时（{request_timeout:g} 秒）"
            ) from exc
        except requests.ConnectionError as exc:
            raise ApiClientError(f"无法连接后端：{self.base_url}") from exc
        except requests.RequestException as exc:
            raise ApiClientError(f"后端请求失败：{exc}") from exc

        return self._unwrap_response(response)

    def _unwrap_response(self, response: requests.Response) -> Any:
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
            if response.status_code == 401 and self.access_token:
                self.access_token = None
                if self.on_auth_failure is not None:
                    self.on_auth_failure()
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

    def login(self, identity: str, password: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/auth/login",
            json={"identity": identity, "password": password},
        )
        if not isinstance(data, dict) or not isinstance(
            data.get("access_token"), str
        ):
            raise ApiClientError("登录响应格式错误")
        self.access_token = data["access_token"]
        return data

    def register(
        self, username: str, password: str, email: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "username": username,
            "password": password,
        }
        if email:
            payload["email"] = email
        data = self._request("POST", "/api/auth/register", json=payload)
        if not isinstance(data, dict):
            raise ApiClientError("注册响应格式错误")
        return data

    def me(self) -> dict[str, Any]:
        data = self._request("GET", "/api/auth/me")
        if not isinstance(data, dict):
            raise ApiClientError("用户响应格式错误")
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

    def delete_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> dict[str, Any]:
        data = self._request(
            "DELETE",
            f"/api/knowledge-bases/{knowledge_base_id}",
        )
        if not isinstance(data, dict):
            raise ApiClientError("删除知识库响应格式错误")
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

    def list_files(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/api/files",
            params={"knowledge_base_id": knowledge_base_id},
        )
        if not isinstance(data, list):
            raise ApiClientError("文件列表响应格式错误")
        return [item for item in data if isinstance(item, dict)]

    def get_file(self, file_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/api/files/{file_id}")
        if not isinstance(data, dict):
            raise ApiClientError("文件详情响应格式错误")
        return data

    def process_file(self, file_id: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            f"/api/files/{file_id}/process",
            _timeout_seconds=self.stream_timeout_seconds,
        )
        if not isinstance(data, dict):
            raise ApiClientError("文件处理响应格式错误")
        return data

    def get_job(self, job_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/api/jobs/{job_id}")
        if not isinstance(data, dict):
            raise ApiClientError("Job 响应格式错误")
        return data

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> dict[str, Any]:
        timeout = timeout_seconds or self.stream_timeout_seconds
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if job.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                return job
            if time.monotonic() >= deadline:
                raise ApiClientError(f"等待 Job 超时（{timeout:g} 秒）")
            time.sleep(poll_interval_seconds)

    def delete_file(self, file_id: str) -> dict[str, Any]:
        data = self._request("DELETE", f"/api/files/{file_id}")
        if not isinstance(data, dict):
            raise ApiClientError("文件删除响应格式错误")
        return data

    def create_session(
        self,
        knowledge_base_id: str,
        title: str = "新会话",
    ) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/sessions",
            json={
                "knowledge_base_id": knowledge_base_id,
                "title": title,
            },
        )
        if not isinstance(data, dict):
            raise ApiClientError("创建会话响应格式错误")
        return data

    def list_sessions(
        self,
        knowledge_base_id: str,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/api/sessions",
            params={"knowledge_base_id": knowledge_base_id},
        )
        if not isinstance(data, list):
            raise ApiClientError("会话列表响应格式错误")
        return [item for item in data if isinstance(item, dict)]

    def get_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/api/sessions/{session_id}",
            params={"knowledge_base_id": knowledge_base_id},
        )
        if not isinstance(data, dict):
            raise ApiClientError("会话详情响应格式错误")
        return data

    def list_messages(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/api/sessions/{session_id}/messages",
            params={"knowledge_base_id": knowledge_base_id},
        )
        if not isinstance(data, list):
            raise ApiClientError("历史消息响应格式错误")
        return [item for item in data if isinstance(item, dict)]

    def delete_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        data = self._request(
            "DELETE",
            f"/api/sessions/{session_id}",
            params={"knowledge_base_id": knowledge_base_id},
        )
        if not isinstance(data, dict):
            raise ApiClientError("删除会话响应格式错误")
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

    def stream_chat(
        self,
        knowledge_base_id: str,
        question: str,
        *,
        session_id: str,
        top_k: int = 4,
    ) -> Iterator[dict[str, Any]]:
        """Yield validated NDJSON events and always close the HTTP stream."""

        url = f"{self.base_url}/api/chat/stream"
        try:
            response = requests.request(
                method="POST",
                url=url,
                json={
                    "knowledge_base_id": knowledge_base_id,
                    "session_id": session_id,
                    "question": question,
                    "top_k": top_k,
                },
                stream=True,
                timeout=(
                    self.timeout_seconds,
                    self.stream_timeout_seconds,
                ),
                **self._authenticated_kwargs({}),
            )
        except requests.Timeout as exc:
            raise ApiClientError("建立流式回答连接超时") from exc
        except requests.ConnectionError as exc:
            raise ApiClientError(f"无法连接后端：{self.base_url}") from exc
        except requests.RequestException as exc:
            raise ApiClientError(f"流式回答请求失败：{exc}") from exc

        started = False
        completed = False
        try:
            if not response.ok:
                self._unwrap_response(response)
            try:
                lines = response.iter_lines(decode_unicode=False)
                for raw_line in lines:
                    if not raw_line:
                        continue
                    try:
                        line = (
                            raw_line.decode("utf-8")
                            if isinstance(raw_line, bytes)
                            else str(raw_line)
                        )
                        event = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ApiClientError("流式响应包含无效 JSON") from exc
                    self._validate_stream_event(event)
                    if completed:
                        raise ApiClientError("流式 done 事件后仍包含数据")
                    if event["type"] == "start":
                        if started:
                            raise ApiClientError("流式 start 事件重复")
                        if event["session_id"] != session_id:
                            raise ApiClientError("流式会话 ID 与请求不一致")
                        started = True
                    elif not started:
                        raise ApiClientError("流式响应缺少 start 事件")
                    if event["type"] == "error":
                        message = str(event.get("message") or "流式回答失败")
                        code = event.get("code")
                        suffix = f"（业务码 {code}）" if code is not None else ""
                        raise ApiClientError(message + suffix)
                    if event["type"] == "done":
                        if event.get("session_id") not in {None, session_id}:
                            raise ApiClientError("流式 done 会话 ID 不一致")
                        completed = True
                    yield event
            except requests.Timeout as exc:
                raise ApiClientError("流式回答读取超时") from exc
            except requests.RequestException as exc:
                raise ApiClientError("流式回答连接中断") from exc
            if not completed:
                raise ApiClientError("流式回答未正常结束")
        finally:
            response.close()

    @staticmethod
    def _validate_stream_event(event: Any) -> None:
        if not isinstance(event, dict):
            raise ApiClientError("流式事件格式错误")
        event_type = event.get("type")
        if event_type not in {"start", "delta", "sources", "done", "error"}:
            raise ApiClientError("流式事件类型无效")
        if event_type == "start" and not isinstance(
            event.get("session_id"), str
        ):
            raise ApiClientError("流式 start 事件缺少会话 ID")
        if event_type == "delta" and not isinstance(
            event.get("content"), str
        ):
            raise ApiClientError("流式 delta 事件缺少正文")
        if event_type == "sources" and not isinstance(
            event.get("sources"), list
        ):
            raise ApiClientError("流式 sources 事件格式错误")
        if event_type == "done" and not isinstance(
            event.get("message_id"), str
        ):
            raise ApiClientError("流式 done 事件缺少消息 ID")
        if event_type == "error" and not isinstance(
            event.get("message"), str
        ):
            raise ApiClientError("流式 error 事件缺少错误信息")


def api_client_from_env() -> ApiClient:
    """从环境变量或项目根目录的 ``.env`` 创建客户端。"""

    try:
        settings = UiSettings()
    except ValidationError as exc:
        raise ApiClientError("前端 API 配置无效，请检查 .env") from exc
    return ApiClient(
        base_url=settings.API_BASE_URL,
        timeout_seconds=settings.API_TIMEOUT_SECONDS,
        stream_timeout_seconds=settings.API_STREAM_TIMEOUT_SECONDS,
    )

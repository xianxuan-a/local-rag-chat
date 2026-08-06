"""HTTP-only UI client behavior, including NDJSON stream cleanup."""

from __future__ import annotations

import json

import pytest
import requests

from ui.api_client import ApiClient, ApiClientError


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload=None,
        events: list[dict] | None = None,
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self._payload = payload
        self._events = events or []
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def iter_lines(self, *, decode_unicode: bool):
        assert decode_unicode is False
        for event in self._events:
            yield json.dumps(event, ensure_ascii=False).encode("utf-8")

    def close(self) -> None:
        self.closed = True


def _client() -> ApiClient:
    return ApiClient(
        "http://backend.test",
        timeout_seconds=2,
        stream_timeout_seconds=30,
    )


def test_management_methods_use_central_http_client(monkeypatch) -> None:
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return FakeResponse(
            payload={
                "code": 0,
                "message": "success",
                "data": {"id": "resource-id"},
            }
        )

    monkeypatch.setattr("ui.api_client.requests.request", fake_request)
    client = _client()

    assert client.delete_knowledge_base("kb-id")["id"] == "resource-id"
    assert client.process_file("file-id")["id"] == "resource-id"

    assert calls[0]["url"].endswith("/api/knowledge-bases/kb-id")
    assert calls[0]["method"] == "DELETE"
    assert calls[1]["url"].endswith("/api/files/file-id/process")
    assert calls[1]["method"] == "POST"
    assert calls[1]["timeout"] == 30


def test_unauthorized_response_clears_token_and_notifies_ui(
    monkeypatch,
) -> None:
    notifications: list[str] = []
    response = FakeResponse(
        status_code=401,
        payload={
            "code": 401,
            "message": "用户已禁用",
            "data": None,
        },
    )
    monkeypatch.setattr(
        "ui.api_client.requests.request",
        lambda **_kwargs: response,
    )
    client = ApiClient(
        "http://backend.test",
        access_token="expired-token",
        on_auth_failure=lambda: notifications.append("cleared"),
    )

    with pytest.raises(ApiClientError, match="用户已禁用.*401"):
        client.me()

    assert client.access_token is None
    assert notifications == ["cleared"]


def test_stream_chat_parses_structured_events_and_closes(monkeypatch) -> None:
    response = FakeResponse(
        events=[
            {"type": "start", "session_id": "session-id"},
            {"type": "delta", "content": "真实"},
            {"type": "delta", "content": "增量"},
            {"type": "sources", "sources": []},
            {"type": "done", "message_id": "message-id"},
        ]
    )
    monkeypatch.setattr(
        "ui.api_client.requests.request",
        lambda **_kwargs: response,
    )

    events = list(
        _client().stream_chat(
            "kb-id",
            "问题",
            session_id="session-id",
        )
    )

    assert [event["type"] for event in events] == [
        "start",
        "delta",
        "delta",
        "sources",
        "done",
    ]
    assert response.closed is True


def test_stream_error_event_becomes_client_error_and_closes(
    monkeypatch,
) -> None:
    response = FakeResponse(
        events=[
            {"type": "start", "session_id": "session-id"},
            {"type": "error", "message": "模型不可用", "code": 503},
        ]
    )
    monkeypatch.setattr(
        "ui.api_client.requests.request",
        lambda **_kwargs: response,
    )

    with pytest.raises(ApiClientError, match="模型不可用.*503"):
        list(
            _client().stream_chat(
                "kb-id",
                "问题",
                session_id="session-id",
            )
        )

    assert response.closed is True


def test_truncated_stream_is_rejected_and_closed(monkeypatch) -> None:
    response = FakeResponse(
        events=[
            {"type": "start", "session_id": "session-id"},
            {"type": "delta", "content": "未完成"},
        ]
    )
    monkeypatch.setattr(
        "ui.api_client.requests.request",
        lambda **_kwargs: response,
    )

    with pytest.raises(ApiClientError, match="未正常结束"):
        list(
            _client().stream_chat(
                "kb-id",
                "问题",
                session_id="session-id",
            )
        )

    assert response.closed is True


def test_consumer_close_releases_stream_response(monkeypatch) -> None:
    response = FakeResponse(
        events=[
            {"type": "start", "session_id": "session-id"},
            {"type": "delta", "content": "后续内容"},
            {"type": "done", "message_id": "message-id"},
        ]
    )
    monkeypatch.setattr(
        "ui.api_client.requests.request",
        lambda **_kwargs: response,
    )
    events = _client().stream_chat(
        "kb-id",
        "问题",
        session_id="session-id",
    )

    assert next(events)["type"] == "start"
    events.close()

    assert response.closed is True


def test_stream_network_error_is_not_hidden(monkeypatch) -> None:
    def fail_request(**_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("ui.api_client.requests.request", fail_request)

    with pytest.raises(ApiClientError, match="无法连接后端"):
        list(
            _client().stream_chat(
                "kb-id",
                "问题",
                session_id="session-id",
            )
        )

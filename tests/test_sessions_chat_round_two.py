"""P1 round-two session, retry, feedback, concurrency, and recovery tests."""

from __future__ import annotations

from uuid import uuid4

from dashscope.common.error import RequestFailure
from fastapi.testclient import TestClient

from app.database.migrations import upgrade_database
from app.main import create_app
from app.models import MessageRole, MessageStatus
from app.repositories.session_repository import SessionRepository
from app.services.chat_history_service import ChatHistoryService
from tests.conftest import make_test_settings
from tests.test_streaming_chat_api import (
    _parse_events,
    _prepare_indexed_knowledge_base,
    _stream_response,
)


def _create_session(
    client: TestClient,
    knowledge_base_id: str,
    title: str,
) -> dict:
    response = client.post(
        "/api/sessions",
        json={"knowledge_base_id": knowledge_base_id, "title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_session_pagination_patch_summary_and_stable_history(
    client: TestClient,
) -> None:
    knowledge_base_id = client.post(
        "/api/knowledge-bases",
        json={"name": "round-two-sessions"},
    ).json()["data"]["id"]
    created = [
        _create_session(client, knowledge_base_id, f"会话 {index}")
        for index in range(4)
    ]

    first_page = client.get(
        "/api/sessions",
        params={"limit": 2, "offset": 0},
    )
    second_page = client.get(
        "/api/sessions",
        params={"limit": 2, "offset": 2},
    )
    assert first_page.status_code == second_page.status_code == 200
    first_ids = [item["id"] for item in first_page.json()["data"]]
    second_ids = [item["id"] for item in second_page.json()["data"]]
    assert len(first_ids) == len(second_ids) == 2
    assert set(first_ids).isdisjoint(second_ids)

    target = created[0]
    updated = client.patch(
        f"/api/sessions/{target['id']}",
        params={"knowledge_base_id": knowledge_base_id},
        json={"title": "  修改后的标题  "},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "修改后的标题"
    assert updated.json()["data"]["message_count"] == 0
    assert updated.json()["data"]["preview"] == "尚未开始对话"

    blank = client.patch(
        f"/api/sessions/{target['id']}",
        params={"knowledge_base_id": knowledge_base_id},
        json={"title": "   "},
    )
    assert blank.status_code == 422
    assert client.get(
        f"/api/sessions/{target['id']}/messages",
        params={
            "knowledge_base_id": knowledge_base_id,
            "limit": 501,
        },
    ).status_code == 422


def test_feedback_retry_in_place_and_failed_retry_preserves_success(
    client: TestClient,
    app,
    test_settings,
    monkeypatch,
) -> None:
    knowledge_base_id, file_id = _prepare_indexed_knowledge_base(
        client,
        app,
        test_settings,
        "round-two-retry",
    )
    session = _create_session(client, knowledge_base_id, "可重试会话")
    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: iter([_stream_response("第一版 [K1]")]),
    )
    first_response = client.post(
        "/api/chat/stream",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": session["id"],
            "question": "请回答",
            "top_k": 4,
        },
    )
    events = _parse_events(first_response)
    start = events[0]
    done = events[-1]
    assert start["type"] == "start"
    assert done["type"] == "done"
    assert start["assistant_message_id"] == done["assistant_message_id"]
    assert events[-2]["sources"][0]["citation_number"] == 1
    assert events[-2]["sources"][0]["file_id"] == file_id
    assistant_id = start["assistant_message_id"]
    user_id = start["user_message_id"]

    feedback_path = (
        f"/api/sessions/{session['id']}/messages/{assistant_id}/feedback"
    )
    params = {"knowledge_base_id": knowledge_base_id}
    for value in ("like", "like", "dislike"):
        feedback = client.put(
            feedback_path,
            params=params,
            json={"value": value},
        )
        assert feedback.status_code == 200
        assert feedback.json()["data"]["value"] == value
    cleared = client.put(
        feedback_path,
        params=params,
        json={"value": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["data"]["value"] is None

    history = client.get(
        f"/api/sessions/{session['id']}/messages",
        params=params,
    ).json()["data"]
    user_message_id = history[0]["id"]
    assert client.put(
        (
            f"/api/sessions/{session['id']}/messages/"
            f"{user_message_id}/feedback"
        ),
        params=params,
        json={"value": "like"},
    ).status_code == 409

    client.put(feedback_path, params=params, json={"value": "like"})
    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: iter([_stream_response("第二版 [K1]")]),
    )
    retry = client.post(
        f"/api/chat/messages/{assistant_id}/retry/stream",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": session["id"],
            "top_k": 4,
        },
    )
    retry_events = _parse_events(retry)
    assert retry_events[0]["type"] == "start"
    assert retry_events[0]["session_id"] == session["id"]
    assert retry_events[0]["user_message_id"] == user_id
    assert retry_events[0]["assistant_message_id"] == assistant_id
    assert retry_events[0]["retry"] is True
    assert retry_events[0]["requested_mode"] == "knowledge_first"
    history = client.get(
        f"/api/sessions/{session['id']}/messages",
        params=params,
    ).json()["data"]
    assert len(history) == 2
    assert history[1]["id"] == assistant_id
    assert history[1]["reply_to_message_id"] == user_id
    assert history[1]["content"] == "第二版 [K1]"
    assert history[1]["status"] == "complete"
    assert history[1]["feedback"] is None

    client.put(feedback_path, params=params, json={"value": "like"})

    def broken_stream():
        raise RequestFailure(
            request_id="retry-request",
            message="provider unavailable",
            name="ServiceUnavailable",
            http_code=503,
        )
        yield  # pragma: no cover

    monkeypatch.setattr(
        "app.services.chat_model_service.Generation.call",
        lambda **_kwargs: broken_stream(),
    )
    failed_retry = client.post(
        f"/api/chat/messages/{assistant_id}/retry/stream",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": session["id"],
            "top_k": 4,
        },
    )
    assert [event["type"] for event in _parse_events(failed_retry)] == [
        "start",
        "retrieval",
        "error",
    ]
    preserved = client.get(
        f"/api/sessions/{session['id']}/messages",
        params=params,
    ).json()["data"][1]
    assert preserved["content"] == "第二版 [K1]"
    assert preserved["status"] == "complete"
    assert preserved["feedback"] == "like"


def test_same_session_occupancy_blocks_mutations_but_not_other_session(
    client: TestClient,
    app,
) -> None:
    knowledge_base_id = client.post(
        "/api/knowledge-bases",
        json={"name": "round-two-concurrency"},
    ).json()["data"]["id"]
    first = _create_session(client, knowledge_base_id, "第一会话")
    second = _create_session(client, knowledge_base_id, "第二会话")
    runtime = app.state.rag_runtime
    runtime.begin_chat(first["id"])
    try:
        conflict = client.post(
            "/api/chat",
            json={
                "knowledge_base_id": knowledge_base_id,
                "session_id": first["id"],
                "question": "并发问题",
            },
        )
        assert conflict.status_code == 409
        assert client.patch(
            f"/api/sessions/{first['id']}",
            params={"knowledge_base_id": knowledge_base_id},
            json={"title": "不应修改"},
        ).status_code == 409
        assert client.delete(
            f"/api/sessions/{first['id']}",
            params={"knowledge_base_id": knowledge_base_id},
        ).status_code == 409
        isolated = client.patch(
            f"/api/sessions/{second['id']}",
            params={"knowledge_base_id": knowledge_base_id},
            json={"title": "可独立修改"},
        )
        assert isolated.status_code == 200
    finally:
        runtime.end_chat(first["id"])
    assert runtime.is_chat_active(first["id"]) is False


def test_explicit_stream_cancel_targets_exact_owned_answer(
    client: TestClient,
    app,
) -> None:
    knowledge_base_id = client.post(
        "/api/knowledge-bases",
        json={"name": "round-two-explicit-cancel"},
    ).json()["data"]["id"]
    session = _create_session(client, knowledge_base_id, "显式停止")
    runtime = app.state.rag_runtime
    runtime.begin_chat(session["id"])
    try:
        with app.state.session_factory() as db:
            history = ChatHistoryService(db)
            turn = history.start_turn(
                knowledge_base_id,
                session["id"],
                "需要停止的问题",
            )
            assistant_id = turn.assistant_message.id
        runtime.bind_chat_message(session["id"], assistant_id)

        wrong_target = client.post(
            f"/api/chat/messages/{uuid4()}/cancel",
            json={
                "knowledge_base_id": knowledge_base_id,
                "session_id": session["id"],
            },
        )
        assert wrong_target.status_code == 404
        assert (
            runtime.is_chat_cancel_requested(session["id"], assistant_id)
            is False
        )

        cancelled = client.post(
            f"/api/chat/messages/{assistant_id}/cancel",
            json={
                "knowledge_base_id": knowledge_base_id,
                "session_id": session["id"],
            },
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"] == {
            "session_id": session["id"],
            "assistant_message_id": assistant_id,
            "cancel_requested": True,
        }
        assert (
            runtime.is_chat_cancel_requested(session["id"], assistant_id)
            is True
        )

        with app.state.session_factory() as db:
            ChatHistoryService(db).cancel_turn(
                knowledge_base_id,
                turn,
                partial_content="已生成的部分",
            )
    finally:
        runtime.end_chat(session["id"])

    repeated = client.post(
        f"/api/chat/messages/{assistant_id}/cancel",
        json={
            "knowledge_base_id": knowledge_base_id,
            "session_id": session["id"],
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["cancel_requested"] is False

    history = client.get(
        f"/api/sessions/{session['id']}/messages",
        params={"knowledge_base_id": knowledge_base_id},
    ).json()["data"]
    assert history[-1]["status"] == "cancelled"
    assert history[-1]["content"] == "已生成的部分"


def _login(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login",
        json={
            "identity": "restart-admin@example.com",
            "password": "test-password-123",
        },
    )
    assert login.status_code == 200, login.text
    client.headers.update(
        {
            "Authorization": (
                f"Bearer {login.json()['data']['access_token']}"
            )
        }
    )


def test_restart_recovers_orphaned_streaming_message(tmp_path) -> None:
    settings = make_test_settings(tmp_path)
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    first_app = create_app(settings)
    with TestClient(first_app, raise_server_exceptions=False) as client:
        bootstrap = client.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "test-bootstrap-secret"},
            json={
                "username": "restart-admin",
                "email": "restart-admin@example.com",
                "password": "test-password-123",
            },
        )
        assert bootstrap.status_code == 200
        _login(client)
        knowledge_base_id = client.post(
            "/api/knowledge-bases",
            json={"name": "restart-chat"},
        ).json()["data"]["id"]
        session = _create_session(client, knowledge_base_id, "重启恢复")
        with first_app.state.session_factory() as db:
            repository = SessionRepository(db)
            user_message = repository.save_message(
                session["id"],
                MessageRole.USER,
                "服务重启前的问题",
            )
            repository.save_message(
                session["id"],
                MessageRole.ASSISTANT,
                "已生成的部分",
                status=MessageStatus.STREAMING,
                reply_to_message_id=user_message.id,
            )
            db.commit()

    restarted_app = create_app(settings)
    with TestClient(restarted_app, raise_server_exceptions=False) as client:
        _login(client)
        history = client.get(
            f"/api/sessions/{session['id']}/messages",
            params={"knowledge_base_id": knowledge_base_id},
        )
        assert history.status_code == 200
        assistant = history.json()["data"][1]
        assert assistant["content"] == "已生成的部分"
        assert assistant["status"] == "failed"
        assert assistant["error_code"] == "ORPHANED_STREAMING_MESSAGE"

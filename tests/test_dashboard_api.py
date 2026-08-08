"""Authenticated Dashboard aggregation, scope, and continuity tests."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import (
    ChatSession,
    FileRecord,
    FileStatus,
    Job,
    JobStatus,
    JobType,
    KnowledgeBase,
    MessageRole,
    MessageStatus,
)
from app.repositories.session_repository import SessionRepository
from app.services.dashboard_service import DashboardService


def _register_and_login(client, username: str) -> str:
    password = f"{username}-password-123"
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    login = client.post(
        "/api/auth/login",
        json={"identity": username, "password": password},
    )
    assert login.status_code == 200, login.text
    return login.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_empty_snapshot_is_continuous_and_secret_safe(client) -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    snapshot = response.json()["data"]
    assert snapshot["time_zone"] == "UTC"
    assert snapshot["window_days"] == 7
    assert len(snapshot["trend"]) == 7
    assert [point["date"] for point in snapshot["trend"]] == sorted(
        point["date"] for point in snapshot["trend"]
    )
    assert all(
        sum(
            point[key]
            for key in (
                "uploads",
                "questions",
                "failed_files",
                "index_operations",
                "evaluation_runs",
            )
        )
        == 0
        for point in snapshot["trend"]
    )
    assert snapshot["metrics"]["knowledge_bases"] == 0
    assert snapshot["metrics"]["files_total"] == 0
    assert {item["status"]: item["count"] for item in snapshot["file_statuses"]} == {
        "PENDING": 0,
        "PROCESSING": 0,
        "SUCCESS": 0,
        "FAILED": 0,
    }
    assert "api_key" not in str(snapshot).casefold()
    assert set(snapshot["runtime"]) == {
        "chat_configured",
        "missing_chat_configuration",
        "embedding_key_configured",
    }
    assert snapshot["runtime"] == {
        "chat_configured": False,
        "missing_chat_configuration": ["CHAT_MODEL", "CHAT_CREDENTIAL"],
        "embedding_key_configured": False,
    }

    assert client.get(
        "/api/dashboard", params={"window_days": 31}
    ).status_code == 422
    assert client.get(
        "/api/dashboard", params={"recent_limit": 0}
    ).status_code == 422


def test_dashboard_aggregates_real_rows_and_bounded_recent_records(
    client, app
) -> None:
    knowledge_base = client.post(
        "/api/knowledge-bases",
        json={"name": "Dashboard 数据"},
    ).json()["data"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base["id"]},
        files={"file": ("dashboard.txt", b"dashboard data", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["data"]["id"]
    session = client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": knowledge_base["id"],
            "title": "Dashboard 会话",
        },
    ).json()["data"]
    user_id = client.get("/api/auth/me").json()["data"]["id"]
    now = datetime.now(timezone.utc)

    with app.state.session_factory() as db:
        kb = db.get(KnowledgeBase, knowledge_base["id"])
        assert kb is not None
        kb.active_collection_name = "dashboard-active"
        file_record = db.get(FileRecord, file_id)
        assert file_record is not None
        file_record.status = FileStatus.SUCCESS
        file_record.chunk_count = 3
        history = SessionRepository(db)
        user_message = history.save_message(
            session["id"],
            MessageRole.USER,
            "Dashboard 最近问题",
            status=MessageStatus.COMPLETE,
        )
        history.save_message(
            session["id"],
            MessageRole.ASSISTANT,
            "Dashboard 最近回答",
            status=MessageStatus.COMPLETE,
            reply_to_message_id=user_message.id,
        )
        chat_session = db.get(ChatSession, session["id"])
        assert chat_session is not None
        chat_session.updated_at = now
        db.add_all(
            [
                Job(
                    job_type=JobType.KB_REBUILD.value,
                    status=JobStatus.SUCCEEDED.value,
                    created_by_id=user_id,
                    resource_type="KNOWLEDGE_BASE",
                    resource_id=knowledge_base["id"],
                    resource_name_snapshot=knowledge_base["name"],
                    progress=100,
                    stage="SUCCEEDED",
                    run_after=now,
                    finished_at=now,
                ),
                Job(
                    job_type=JobType.RAG_EVALUATION.value,
                    status=JobStatus.FAILED.value,
                    created_by_id=user_id,
                    resource_type="KNOWLEDGE_BASE",
                    resource_id=knowledge_base["id"],
                    resource_name_snapshot=knowledge_base["name"],
                    progress=40,
                    stage="EVALUATING",
                    error_message="受控失败",
                    run_after=now,
                    finished_at=now,
                    evaluation_mode="retrieval",
                    evaluation_run_name="Dashboard 评测",
                ),
            ]
        )
        db.commit()

    response = client.get(
        "/api/dashboard",
        params={
            "knowledge_base_id": knowledge_base["id"],
            "window_days": 7,
            "recent_limit": 1,
        },
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()["data"]
    metrics = snapshot["metrics"]
    assert metrics == {
        "knowledge_bases": 1,
        "files_total": 1,
        "files_success": 1,
        "files_in_progress": 0,
        "files_failed": 0,
        "chunks": 3,
        "sessions": 1,
        "user_questions": 1,
        "assistant_answers": 1,
        "active_indexes": 1,
        "building_indexes": 0,
    }
    assert snapshot["trend"][-1]["uploads"] == 1
    assert snapshot["trend"][-1]["questions"] == 1
    assert snapshot["trend"][-1]["index_operations"] == 1
    assert snapshot["trend"][-1]["evaluation_runs"] == 1
    assert snapshot["recent_files"][0]["id"] == file_id
    assert snapshot["recent_sessions"][0]["id"] == session["id"]
    assert snapshot["recent_sessions"][0]["preview"] == "Dashboard 最近回答"
    assert snapshot["recent_index_jobs"][0]["job_type"] == "KB_REBUILD"
    assert snapshot["recent_evaluations"][0]["status"] == "FAILED"
    assert snapshot["recent_evaluations"][0]["error_message"] == "受控失败"


def test_dashboard_hides_other_users_and_admin_retains_global_visibility(
    client,
) -> None:
    alice = _register_and_login(client, "dashboard-alice")
    bob = _register_and_login(client, "dashboard-bob")
    created = client.post(
        "/api/knowledge-bases",
        headers=_auth(alice),
        json={"name": "Alice Dashboard"},
    )
    assert created.status_code == 201, created.text
    knowledge_base_id = created.json()["data"]["id"]

    hidden = client.get(
        "/api/dashboard",
        headers=_auth(bob),
        params={"knowledge_base_id": knowledge_base_id},
    )
    assert hidden.status_code == 404
    bob_global = client.get("/api/dashboard", headers=_auth(bob))
    assert bob_global.status_code == 200
    assert bob_global.json()["data"]["metrics"]["knowledge_bases"] == 0

    admin_global = client.get("/api/dashboard")
    assert admin_global.status_code == 200
    assert admin_global.json()["data"]["metrics"]["knowledge_bases"] == 1


def test_dashboard_surfaces_noncritical_section_failure(
    client, monkeypatch
) -> None:
    def fail_recent_files(*_args, **_kwargs):
        raise RuntimeError("controlled section failure")

    monkeypatch.setattr(
        DashboardService,
        "_recent_files",
        fail_recent_files,
    )
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    snapshot = response.json()["data"]
    assert snapshot["recent_files"] == []
    assert snapshot["section_errors"] == {
        "recent_files": "该区域暂时不可用，请刷新后重试"
    }
    assert len(snapshot["trend"]) == 7

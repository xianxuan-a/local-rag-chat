"""RBAC user-management, live token, and persistent audit tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import User, UserAdminAuditEvent, UserRole


def _register_and_login(client, username: str) -> tuple[str, str]:
    password = "password-eight"
    registered = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login",
        json={"identity": username, "password": password},
    )
    assert login.status_code == 200, login.text
    return (
        login.json()["data"]["user"]["id"],
        login.json()["data"]["access_token"],
    )


def test_admin_user_management_is_live_and_persistently_audited(client, app) -> None:
    admin = client.get("/api/auth/me").json()["data"]
    target_id, target_token = _register_and_login(client, "managed-user")
    target_headers = {"Authorization": f"Bearer {target_token}"}

    forbidden = client.get("/api/users", headers=target_headers)
    assert forbidden.status_code == 403

    listed = client.get("/api/users?limit=1&offset=0&query=managed")
    assert listed.status_code == 200, listed.text
    page = listed.json()["data"]
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["limit"] == 1

    promoted = client.patch(
        f"/api/users/{target_id}",
        json={"role": "ADMIN", "reason": "coverage promotion"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["data"]["role"] == "ADMIN"

    live_admin = client.get("/api/users", headers=target_headers)
    assert live_admin.status_code == 200, live_admin.text

    demoted = client.patch(
        f"/api/users/{target_id}",
        json={"role": "USER", "reason": "coverage demotion"},
    )
    assert demoted.status_code == 200, demoted.text
    assert client.get("/api/users", headers=target_headers).status_code == 403

    disabled = client.patch(
        f"/api/users/{target_id}",
        json={"is_active": False, "reason": "coverage disable"},
    )
    assert disabled.status_code == 200, disabled.text
    assert client.get("/api/auth/me", headers=target_headers).status_code == 401

    self_change = client.patch(
        f"/api/users/{admin['id']}",
        json={"role": "USER"},
    )
    assert self_change.status_code == 409

    audit = client.get(f"/api/users/audit-events?target_user_id={target_id}")
    assert audit.status_code == 200, audit.text
    events = audit.json()["data"]
    assert events["total"] == 3
    assert {item["action"] for item in events["items"]} == {"USER_UPDATED"}
    assert all(item["actor_user_id"] == admin["id"] for item in events["items"])
    assert {item["reason"] for item in events["items"]} == {
        "coverage promotion",
        "coverage demotion",
        "coverage disable",
    }

    with app.state.session_factory() as db:
        assert db.scalar(select(UserAdminAuditEvent).limit(1)) is not None


def test_database_trigger_preserves_the_last_active_admin(client, app) -> None:
    admin_id = client.get("/api/auth/me").json()["data"]["id"]
    with app.state.session_factory() as db:
        admin = db.get(User, admin_id)
        assert admin is not None
        admin.role = UserRole.USER.value
        with pytest.raises(IntegrityError, match="last_active_admin"):
            db.commit()
        db.rollback()


def test_user_update_requires_a_real_change(client) -> None:
    target_id, _ = _register_and_login(client, "validation-user")
    empty = client.patch(f"/api/users/{target_id}", json={"reason": "none"})
    assert empty.status_code == 422

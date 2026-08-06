"""Server-side ownership, hidden 404, Job ownership, and admin-only maintenance."""

from __future__ import annotations


def _register_and_login(client, username: str) -> str:
    password = f"{username}-password-123"
    registered = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"identity": username.upper(), "password": password},
    )
    assert login.status_code == 200
    return login.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_resource_chain_and_admin_only_maintenance(client) -> None:
    alice_token = _register_and_login(client, "alice-owner")
    bob_token = _register_and_login(client, "bob-owner")

    alice_kb = client.post(
        "/api/knowledge-bases",
        headers=_auth(alice_token),
        json={"name": "alice-private"},
    )
    assert alice_kb.status_code == 201
    knowledge_base_id = alice_kb.json()["data"]["id"]
    assert client.get(
        f"/api/knowledge-bases/{knowledge_base_id}",
        headers=_auth(bob_token),
    ).status_code == 404
    assert client.get(
        f"/api/knowledge-bases/{knowledge_base_id}"
    ).status_code == 200

    uploaded = client.post(
        "/api/files/upload",
        headers=_auth(alice_token),
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("private.txt", b"private", "text/plain")},
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["data"]["id"]
    assert client.get(
        f"/api/files/{file_id}", headers=_auth(bob_token)
    ).status_code == 404

    session = client.post(
        "/api/sessions",
        headers=_auth(alice_token),
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": "private session",
        },
    )
    assert session.status_code == 201
    session_id = session.json()["data"]["id"]
    assert client.get(
        f"/api/sessions/{session_id}",
        headers=_auth(bob_token),
        params={"knowledge_base_id": knowledge_base_id},
    ).status_code == 404

    submitted = client.post(
        f"/api/files/{file_id}/process", headers=_auth(alice_token)
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["data"]["id"]
    assert client.get(
        f"/api/jobs/{job_id}", headers=_auth(bob_token)
    ).status_code == 404

    assert client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/rebuild",
        headers=_auth(alice_token),
    ).status_code == 403
    assert client.post(
        "/api/backups", headers=_auth(alice_token)
    ).status_code == 403
    assert client.put(
        "/api/settings",
        headers=_auth(alice_token),
        json={
            "chat_model": None,
            "retrieval_top_k": 5,
            "retrieval_score_threshold": None,
            "rag_context_max_chars": 12000,
        },
    ).status_code == 403
    assert client.patch(
        f"/api/knowledge-bases/{knowledge_base_id}",
        headers=_auth(bob_token),
        json={"name": "hidden-update"},
    ).status_code == 404
    assert client.post(
        "/api/retrieval",
        headers=_auth(bob_token),
        json={
            "knowledge_base_id": knowledge_base_id,
            "query": "private",
            "top_k": 5,
            "score_threshold": None,
        },
    ).status_code == 404

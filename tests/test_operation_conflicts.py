"""High-value rows from the durable operation-conflict matrix."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.exceptions import ConflictException
from app.models import (
    JobStatus,
    JobType,
    KnowledgeBase,
    RuntimeState,
    User,
    utc_now,
)
from app.services.job_service import JobService
from app.services.file_service import FileService
from tests.conftest import wait_for_job
from tests.fakes import FakeEmbedding


def test_evaluation_pin_backup_draining_and_maintenance_conflicts(
    client,
    app,
) -> None:
    fake = FakeEmbedding()
    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: fake
    store._embedding_cache.clear()

    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "conflict-matrix"}
    ).json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("source.txt", b"pinned content", "text/plain")},
    ).json()["data"]
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == "SUCCEEDED"

    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        admin = db.query(User).filter(User.role == "ADMIN").one()
        assert knowledge_base is not None
        pinned_collection = knowledge_base.active_collection_name
        evaluation = JobService(db).submit(
            job_type=JobType.RAG_EVALUATION,
            created_by_id=admin.id,
            resource_type="KNOWLEDGE_BASE",
            resource_id=knowledge_base.id,
            resource_name_snapshot=knowledge_base.name,
            payload={"case_count": 1},
            collection_name=pinned_collection,
            embedding_config_hash=knowledge_base.active_embedding_config_hash,
            run_after_seconds=3600,
            max_attempts=1,
        )

    assert client.post(f"/api/files/{uploaded['id']}/process").status_code == 409
    assert client.delete(
        f"/api/knowledge-bases/{knowledge_base_id}"
    ).status_code == 409
    assert client.post("/api/backups").status_code == 409

    rebuild = wait_for_job(
        client,
        client.post(f"/api/knowledge-bases/{knowledge_base_id}/rebuild"),
    )
    assert rebuild["status"] == JobStatus.SUCCEEDED.value
    assert client.delete(f"/api/files/{uploaded['id']}").status_code == 409
    assert client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/rollback"
    ).status_code == 409

    with app.state.session_factory() as db:
        with pytest.raises(ConflictException):
            JobService(db).submit(
                job_type=JobType.KB_CLEANUP_RETIRED,
                created_by_id=None,
                resource_type="KNOWLEDGE_BASE",
                resource_id=knowledge_base_id,
                collection_name=pinned_collection,
            )

    cancelled = client.post(f"/api/jobs/{evaluation.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == JobStatus.CANCELLED.value
    assert client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/rollback"
    ).status_code == 200

    with app.state.session_factory() as db:
        db.add(
            RuntimeState(
                key="BACKUP_DRAINING",
                value={"status": "DRAINING"},
                owner_job_id=None,
                lease_expires_at=utc_now() + timedelta(seconds=30),
                updated_at=utc_now(),
            )
        )
        db.commit()
    assert client.get(
        f"/api/knowledge-bases/{knowledge_base_id}"
    ).status_code == 200
    blocked_registration = client.post(
        "/api/auth/register",
        json={
            "username": "draining-user",
            "email": "draining@example.com",
            "password": "draining-password",
        },
    )
    assert blocked_registration.status_code == 409
    assert blocked_registration.headers.get("X-Request-ID")
    with app.state.session_factory() as db:
        state = db.get(RuntimeState, "BACKUP_DRAINING")
        assert state is not None
        db.delete(state)
        db.commit()


def test_queued_rebuild_blocks_synchronous_kb_writes(
    client,
    app,
) -> None:
    fake = FakeEmbedding()
    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: fake
    store._embedding_cache.clear()
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "queued-rebuild-conflicts"}
    ).json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("source.txt", b"queued rebuild", "text/plain")},
    ).json()["data"]
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == JobStatus.SUCCEEDED.value

    with app.state.session_factory() as db:
        admin = db.query(User).filter(User.role == "ADMIN").one()
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        rebuild = JobService(db).submit(
            job_type=JobType.KB_REBUILD,
            created_by_id=admin.id,
            resource_type="KNOWLEDGE_BASE",
            resource_id=knowledge_base.id,
            resource_name_snapshot=knowledge_base.name,
            run_after_seconds=3600,
            max_attempts=2,
        )

    assert client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("blocked.txt", b"blocked", "text/plain")},
    ).status_code == 409
    assert client.post(
        "/api/sessions",
        json={
            "knowledge_base_id": knowledge_base_id,
            "title": "blocked",
        },
    ).status_code == 409
    assert client.delete(f"/api/files/{uploaded['id']}").status_code == 409
    assert client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/rollback"
    ).status_code == 409
    assert client.post(
        f"/api/knowledge-bases/{knowledge_base_id}/abort-building"
    ).status_code == 409

    cancelled = client.post(f"/api/jobs/{rebuild.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == JobStatus.CANCELLED.value
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        assert knowledge_base.rebuild_job_id is None


def test_file_handler_rechecks_evaluation_pin_after_queueing(
    client,
    app,
    test_settings,
) -> None:
    fake = FakeEmbedding()
    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: fake
    store._embedding_cache.clear()
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "late-evaluation-pin"}
    ).json()["data"]["id"]
    first = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("first.txt", b"active vectors", "text/plain")},
    ).json()["data"]
    assert wait_for_job(
        client, client.post(f"/api/files/{first['id']}/process")
    )["status"] == JobStatus.SUCCEEDED.value
    second = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("second.txt", b"must wait", "text/plain")},
    ).json()["data"]

    with app.state.session_factory() as db:
        admin = db.query(User).filter(User.role == "ADMIN").one()
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        file_job = JobService(db).submit(
            job_type=JobType.FILE_PROCESS,
            created_by_id=admin.id,
            resource_type="FILE",
            resource_id=second["id"],
            resource_name_snapshot="second.txt",
            run_after_seconds=3600,
            max_attempts=2,
        )
        evaluation = JobService(db).submit(
            job_type=JobType.RAG_EVALUATION,
            created_by_id=admin.id,
            resource_type="KNOWLEDGE_BASE",
            resource_id=knowledge_base.id,
            resource_name_snapshot=knowledge_base.name,
            payload={"case_count": 1},
            collection_name=knowledge_base.active_collection_name,
            embedding_config_hash=(
                knowledge_base.active_embedding_config_hash
            ),
            run_after_seconds=3600,
            max_attempts=2,
        )

        with pytest.raises(ConflictException, match="pin"):
            FileService(
                db, test_settings, app.state.rag_runtime
            ).process_file(second["id"], job_id=file_job.id)

        service = JobService(db)
        service.cancel(file_job.id)
        service.cancel(evaluation.id)

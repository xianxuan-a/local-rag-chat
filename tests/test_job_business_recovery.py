"""Fault-window tests for business-aware file and rebuild recovery."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from langchain_core.documents import Document

from app.models import (
    FileRecord,
    FileStatus,
    Job,
    JobStatus,
    JobType,
    KnowledgeBase,
    RebuildStatus,
    User,
    utc_now,
)
from app.services.job_recovery_service import (
    JobRecoveryService,
    RecoveryDisposition,
)
from app.services.job_service import JobService
from tests.conftest import wait_for_job
from tests.fakes import FakeEmbedding


def _prepare_index(client, app, *, name: str) -> tuple[str, dict, dict]:
    fake = FakeEmbedding()
    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: fake
    store._embedding_cache.clear()
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": name}
    ).json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("source.txt", b"recovery source", "text/plain")},
    ).json()["data"]
    process_job = wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )
    assert process_job["status"] == JobStatus.SUCCEEDED.value
    return knowledge_base_id, uploaded, process_job


def test_file_recovery_distinguishes_vector_commit_windows(
    client,
    app,
    test_settings,
) -> None:
    knowledge_base_id, uploaded, completed_job = _prepare_index(
        client, app, name="file-recovery"
    )
    with app.state.session_factory() as db:
        completed = db.get(Job, completed_job["id"])
        assert completed is not None
        assert completed.payload["expected_chunk_count"] == 1
        completed.status = JobStatus.RUNNING.value
        completed.lease_owner = "dead-worker"
        completed.lease_expires_at = utc_now() - timedelta(seconds=1)
        completed.finished_at = None
        completed.result = None
        db.commit()
        disposition = JobRecoveryService(
            db, test_settings, app.state.rag_runtime
        ).recover_expired(completed)
        assert disposition is RecoveryDisposition.SUCCEEDED, (
            job.error_code,
            job.error_message,
        )
        assert completed.status == JobStatus.SUCCEEDED.value

    second = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("second.txt", b"vector before database", "text/plain")},
    ).json()["data"]
    with app.state.session_factory() as db:
        admin = db.query(User).filter(User.role == "ADMIN").one()
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        record = db.get(FileRecord, second["id"])
        assert knowledge_base is not None and record is not None
        job = JobService(db).submit(
            job_type=JobType.FILE_PROCESS,
            created_by_id=admin.id,
            resource_type="FILE",
            resource_id=record.id,
            resource_name_snapshot=record.original_name,
            run_after_seconds=3600,
            max_attempts=2,
        )
        job.status = JobStatus.RUNNING.value
        job.attempt = 1
        job.lease_owner = "dead-worker"
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        job.collection_name = knowledge_base.active_collection_name
        job.embedding_config_hash = (
            knowledge_base.active_embedding_config_hash
        )
        job.payload = {
            "expected_chunk_count": 1,
            "vector_run_id": job.id,
        }
        record.status = FileStatus.PROCESSING
        record.processing_job_id = job.id
        db.commit()

        document = Document(
            page_content="vector before database",
            metadata={
                "file_id": record.id,
                "knowledge_base_id": knowledge_base.id,
                "file_name": record.original_name,
                "chunk_id": "chunk-0",
            },
        )
        config = app.state.rag_runtime.vector_store.current_config
        embedding = FakeEmbedding().embed_documents(
            [document.page_content]
        )
        app.state.rag_runtime.vector_store.replace_file_documents(
            collection_name=str(knowledge_base.active_collection_name),
            knowledge_base_id=knowledge_base.id,
            file_id=record.id,
            documents=[document],
            embeddings=embedding,
            config=config,
            role="active",
            processing_job_id=job.id,
            vector_run_id=job.id,
            expected_chunk_count=1,
        )

        disposition = JobRecoveryService(
            db, test_settings, app.state.rag_runtime
        ).recover_expired(job)
        assert disposition is RecoveryDisposition.RETRY_READY
        assert job.status == JobStatus.QUEUED.value
        assert record.status is FileStatus.FAILED
        assert (
            app.state.rag_runtime.vector_store.snapshot_file(
                str(knowledge_base.active_collection_name),
                knowledge_base_id=knowledge_base.id,
                file_id=record.id,
                expected_config_hash=(
                    knowledge_base.active_embedding_config_hash
                ),
            ).ids
            == []
        )


def test_rebuild_recovery_switches_only_a_complete_owned_candidate(
    client,
    app,
    test_settings,
) -> None:
    knowledge_base_id, uploaded, _ = _prepare_index(
        client, app, name="rebuild-recovery"
    )
    store = app.state.rag_runtime.vector_store
    with app.state.session_factory() as db:
        admin = db.query(User).filter(User.role == "ADMIN").one()
        knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
        record = db.get(FileRecord, uploaded["id"])
        assert knowledge_base is not None and record is not None
        old_active = str(knowledge_base.active_collection_name)
        config = store.current_config
        candidate, generation = store.generate_collection_name(
            knowledge_base.id, config.config_hash
        )
        rebuild_run_id = str(uuid4())
        job = JobService(db).submit(
            job_type=JobType.KB_REBUILD,
            created_by_id=admin.id,
            resource_type="KNOWLEDGE_BASE",
            resource_id=knowledge_base.id,
            resource_name_snapshot=knowledge_base.name,
            run_after_seconds=3600,
            max_attempts=2,
        )
        job.status = JobStatus.RUNNING.value
        job.attempt = 1
        job.lease_owner = "dead-worker"
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        job.collection_name = candidate
        job.embedding_config_hash = config.config_hash
        job.payload = {
            "source_collection": old_active,
            "source_previous": knowledge_base.previous_collection_name,
            "rebuild_run_id": rebuild_run_id,
        }
        knowledge_base.building_collection_name = candidate
        knowledge_base.building_embedding_config_hash = config.config_hash
        knowledge_base.rebuild_status = RebuildStatus.BUILDING
        knowledge_base.rebuild_run_id = rebuild_run_id
        knowledge_base.rebuild_job_id = job.id
        knowledge_base.building_started_at = utc_now()
        db.commit()

        store.create_collection(
            name=candidate,
            knowledge_base_id=knowledge_base.id,
            config=config,
            generation=generation,
            lifecycle_status="BUILDING",
        )
        old_snapshot = store.snapshot_file(
            old_active,
            knowledge_base_id=knowledge_base.id,
            file_id=record.id,
            expected_config_hash=config.config_hash,
        )
        documents = [
            Document(page_content=content, metadata=metadata)
            for content, metadata in zip(
                old_snapshot.documents,
                old_snapshot.metadatas,
                strict=True,
            )
        ]
        store.replace_file_documents(
            collection_name=candidate,
            knowledge_base_id=knowledge_base.id,
            file_id=record.id,
            documents=documents,
            embeddings=old_snapshot.embeddings,
            config=config,
            role="building",
            processing_job_id=job.id,
            vector_run_id=rebuild_run_id,
            expected_chunk_count=len(documents),
        )

        disposition = JobRecoveryService(
            db, test_settings, app.state.rag_runtime
        ).recover_expired(job)
        assert disposition is RecoveryDisposition.SUCCEEDED
        assert knowledge_base.active_collection_name == candidate
        assert knowledge_base.previous_collection_name == old_active
        assert knowledge_base.rebuild_status is RebuildStatus.IDLE

        job.status = JobStatus.RUNNING.value
        job.lease_owner = "dead-worker"
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        job.finished_at = None
        db.commit()
        disposition = JobRecoveryService(
            db, test_settings, app.state.rag_runtime
        ).recover_expired(job)
        assert disposition is RecoveryDisposition.SUCCEEDED, (
            job.error_code,
            job.error_message,
        )
        assert job.status == JobStatus.SUCCEEDED.value


def test_startup_recovery_fails_orphaned_processing_record(client, app) -> None:
    knowledge_base_id = client.post(
        "/api/knowledge-bases", json={"name": "orphan-processing"}
    ).json()["data"]["id"]
    uploaded = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": knowledge_base_id},
        files={"file": ("orphan.txt", b"orphan", "text/plain")},
    ).json()["data"]
    with app.state.session_factory() as db:
        record = db.get(FileRecord, uploaded["id"])
        assert record is not None
        record.status = FileStatus.PROCESSING
        record.processing_job_id = None
        db.commit()

    assert app.state.job_worker.recover_orphaned_file_states() == 1
    with app.state.session_factory() as db:
        record = db.get(FileRecord, uploaded["id"])
        assert record is not None
        assert record.status is FileStatus.FAILED
        assert record.processing_job_id is None
        assert record.error_message == "ORPHANED_PROCESSING_STATE"

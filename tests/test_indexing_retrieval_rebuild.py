"""End-to-end file indexing, retrieval, rebuild, and rollback tests."""

from __future__ import annotations

from sqlalchemy.orm import Session
from langchain_core.embeddings import Embeddings

from app.models import FileRecord, FileStatus, KnowledgeBase
from app.core.exceptions import ModelServiceException, VectorStoreException
from app.services.retrieval_service import RetrievalService
from tests.fakes import FakeEmbedding
from tests.conftest import wait_for_job


def _create_kb(client, name: str = "index-kb") -> str:
    response = client.post("/api/knowledge-bases", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _upload(client, kb_id: str, text: str = "stable retrieval text") -> dict:
    response = client.post(
        "/api/files/upload",
        data={"knowledge_base_id": kb_id},
        files={"file": ("source.txt", text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["data"]


def _install_fake(app) -> FakeEmbedding:
    fake = FakeEmbedding()
    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: fake
    store._embedding_cache.clear()
    return fake


def test_process_retrieve_rebuild_and_rollback(client, app, test_settings) -> None:
    fake = _install_fake(app)
    kb_id = _create_kb(client)
    uploaded = _upload(client, kb_id)

    processed = client.post(f"/api/files/{uploaded['id']}/process")
    process_job = wait_for_job(client, processed)
    assert process_job["status"] == "SUCCEEDED"
    assert process_job["result"]["status"] == "SUCCESS"
    assert process_job["result"]["chunk_count"] == 1

    with app.state.session_factory() as db:
        record = db.get(FileRecord, uploaded["id"])
        knowledge_base = db.get(KnowledgeBase, kb_id)
        assert record is not None
        assert record.status is FileStatus.SUCCESS
        assert record.has_active_vectors is True
        assert record.active_index_config_hash
        assert knowledge_base is not None
        first_collection = knowledge_base.active_collection_name
        assert first_collection
        sources = RetrievalService(
            db,
            test_settings,
            app.state.rag_runtime,
        ).retrieve(kb_id, "stable retrieval text")
        assert sources
        assert str(sources[0].file_id) == uploaded["id"]
        assert sources[0].score > 0.99

    rebuilt = client.post(f"/api/knowledge-bases/{kb_id}/rebuild")
    rebuild_job = wait_for_job(client, rebuilt)
    assert rebuild_job["status"] == "SUCCEEDED"
    rebuild_data = rebuild_job["result"]
    assert rebuild_data["status"] == "SUCCESS"
    assert rebuild_data["switched"] is True
    assert rebuild_data["source_collection"] == first_collection
    assert rebuild_data["target_collection"] != first_collection

    rolled_back = client.post(f"/api/knowledge-bases/{kb_id}/rollback")
    assert rolled_back.status_code == 200
    assert rolled_back.json()["data"]["status"] == "SUCCESS"
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, kb_id)
        assert knowledge_base is not None
        assert knowledge_base.active_collection_name == first_collection
    assert fake.document_calls >= 2
    assert fake.query_calls == 1


def test_index_state_api_and_server_resolved_previous_cleanup(
    client, app
) -> None:
    _install_fake(app)
    kb_id = _create_kb(client, "index-state-api")
    uploaded = _upload(client, kb_id, "index state")
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == "SUCCEEDED"
    assert wait_for_job(
        client, client.post(f"/api/knowledge-bases/{kb_id}/rebuild")
    )["status"] == "SUCCEEDED"

    response = client.get(f"/api/indexes?knowledge_base_id={kb_id}")
    assert response.status_code == 200, response.text
    state = response.json()["data"][0]
    assert state["knowledge_base_id"] == kb_id
    by_role = {item["role"]: item for item in state["collections"]}
    assert by_role["active"]["exists"] is True
    assert by_role["active"]["safe_to_cleanup"] is False
    assert by_role["active"]["chunk_count"] == 1
    assert by_role["previous"]["safe_to_cleanup"] is True
    assert state["latest_job"]["job_type"] == "KB_REBUILD"

    cleanup = client.post(
        f"/api/knowledge-bases/{kb_id}/cleanup-retired",
        json={"cleanup_previous": True, "cleanup_orphans": False},
    )
    terminal = wait_for_job(client, cleanup)
    assert terminal["status"] == "SUCCEEDED"
    assert terminal["result"]["deleted"]
    refreshed = client.get(
        f"/api/indexes?knowledge_base_id={kb_id}"
    ).json()["data"][0]
    assert all(
        item["role"] != "previous" for item in refreshed["collections"]
    )
    assert refreshed["latest_job"]["job_type"] == "KB_CLEANUP_RETIRED"


def test_configuration_conflict_happens_before_file_claim(
    client,
    app,
) -> None:
    _install_fake(app)
    kb_id = _create_kb(client, "conflict-kb")
    uploaded = _upload(client, kb_id, "configuration conflict")
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == "SUCCEEDED"

    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, kb_id)
        assert knowledge_base is not None
        knowledge_base.active_embedding_config_hash = "0" * 64
        db.commit()

    response = client.post(f"/api/files/{uploaded['id']}/process")

    assert wait_for_job(client, response)["status"] == "FAILED"
    with app.state.session_factory() as db:
        record = db.get(FileRecord, uploaded["id"])
        assert record is not None
        assert record.status is FileStatus.SUCCESS
        assert record.error_message is None


def test_global_admin_lock_blocks_other_knowledge_base_management(
    client,
    app,
) -> None:
    kb_id = _create_kb(client, "locked-kb")
    lock = app.state.rag_runtime.collection_admin_lock
    acquired = lock.acquire(blocking=False)
    assert acquired
    try:
        # Run from another thread because the lock is deliberately reentrant
        # for nested service operations in the owning request thread.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            response = executor.submit(
                client.post,
                f"/api/knowledge-bases/{kb_id}/rebuild",
            ).result()
            assert response.status_code == 409
            assert "知识库管理操作" in response.json()["message"]
    finally:
        lock.release()


def test_first_embedding_failure_keeps_no_active_vectors(client, app) -> None:
    class FailingEmbedding(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise ModelServiceException("forced embedding failure")

        def embed_query(self, text: str) -> list[float]:
            raise ModelServiceException("forced query failure")

    kb_id = _create_kb(client, "first-failure-kb")
    uploaded = _upload(client, kb_id, "first failure")
    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: FailingEmbedding()
    store._embedding_cache.clear()

    response = client.post(f"/api/files/{uploaded['id']}/process")

    assert wait_for_job(client, response)["status"] == "FAILED"
    with app.state.session_factory() as db:
        record = db.get(FileRecord, uploaded["id"])
        assert record is not None
        assert record.status is FileStatus.FAILED
        assert record.has_active_vectors is False
        assert record.chunk_count == 0
        assert record.active_index_config_hash is None


def test_failed_reprocessing_preserves_old_active_index(client, app) -> None:
    class FailingEmbedding(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise ModelServiceException("forced embedding failure")

        def embed_query(self, text: str) -> list[float]:
            raise ModelServiceException("forced query failure")

    _install_fake(app)
    kb_id = _create_kb(client, "retry-failure-kb")
    uploaded = _upload(client, kb_id, "old index remains")
    assert wait_for_job(
        client, client.post(f"/api/files/{uploaded['id']}/process")
    )["status"] == "SUCCEEDED"
    with app.state.session_factory() as db:
        old = db.get(FileRecord, uploaded["id"])
        assert old is not None
        old_hash = old.active_index_config_hash
        old_time = old.last_successful_indexed_at

    store = app.state.rag_runtime.vector_store
    store._embedding_factory = lambda _: FailingEmbedding()
    store._embedding_cache.clear()
    response = client.post(f"/api/files/{uploaded['id']}/process")

    assert wait_for_job(client, response)["status"] == "FAILED"
    with app.state.session_factory() as db:
        record = db.get(FileRecord, uploaded["id"])
        assert record is not None
        assert record.status is FileStatus.FAILED
        assert record.has_active_vectors is True
        assert record.chunk_count == 1
        assert record.active_index_config_hash == old_hash
        assert record.last_successful_indexed_at == old_time


def test_failed_initial_candidate_is_tracked_and_retried(
    client,
    app,
    monkeypatch,
) -> None:
    _install_fake(app)
    kb_id = _create_kb(client, "candidate-failure-kb")
    uploaded = _upload(client, kb_id, "candidate retry")
    store = app.state.rag_runtime.vector_store
    original_replace = store.replace_file_documents
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise VectorStoreException("forced candidate failure")
        return original_replace(**kwargs)

    monkeypatch.setattr(store, "replace_file_documents", fail_once)
    first = client.post(f"/api/files/{uploaded['id']}/process")
    assert wait_for_job(client, first)["status"] == "FAILED"
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, kb_id)
        record = db.get(FileRecord, uploaded["id"])
        assert knowledge_base is not None
        assert knowledge_base.rebuild_status.value == "FAILED"
        assert knowledge_base.building_collection_name
        failed_collection = knowledge_base.building_collection_name
        assert record is not None and record.status is FileStatus.FAILED

    second = client.post(f"/api/files/{uploaded['id']}/process")

    assert wait_for_job(client, second)["status"] == "SUCCEEDED"
    with app.state.session_factory() as db:
        knowledge_base = db.get(KnowledgeBase, kb_id)
        assert knowledge_base is not None
        assert knowledge_base.active_collection_name
        assert knowledge_base.active_collection_name != failed_collection
        assert knowledge_base.building_collection_name is None
        assert knowledge_base.rebuild_status.value == "IDLE"
    assert not store.collection_exists(failed_collection)

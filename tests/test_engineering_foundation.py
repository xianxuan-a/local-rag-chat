"""Engineering-contract tests for SQLite, auth, leases, and recovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from threading import Barrier
import time

import pytest

from app.core.instance_lock import InstanceLock, InstanceLockError
from app.database.migrations import upgrade_database
from app.database.sqlite import init_database
from app.models import (
    Job,
    JobStatus,
    JobType,
    RuntimeState,
    User,
    UserRole,
    new_uuid,
    utc_now,
)
from app.repositories.job_repository import JobRepository
from app.services.job_recovery_service import (
    JobRecoveryService,
    RecoveryDisposition,
)
from app.services.job_service import JobService
from app.services.job_worker import JobExecutionContext, JobWorker
from app.services.runtime_coordinator import RuntimeCoordinator
from tests.conftest import make_test_settings


def _database(tmp_path: Path):
    settings = make_test_settings(tmp_path)
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    engine, session_factory = init_database(settings.DATABASE_URL)
    return settings, engine, session_factory


def _job(*, status: JobStatus, lease_delta: int | None = None) -> Job:
    now = utc_now()
    return Job(
        id=new_uuid(),
        job_type=JobType.BACKUP.value,
        status=status.value,
        payload={},
        run_after=now,
        lease_owner="worker-a" if lease_delta is not None else None,
        lease_expires_at=(
            now + timedelta(seconds=lease_delta)
            if lease_delta is not None
            else None
        ),
    )


def test_sqlite_runtime_pragmas_and_atomic_claim(tmp_path: Path) -> None:
    _, engine, session_factory = _database(tmp_path)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
            assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 2
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

        queued = _job(status=JobStatus.QUEUED)
        with session_factory() as db:
            db.add(queued)
            db.commit()

        barrier = Barrier(2)

        def claim(owner: str) -> str | None:
            with session_factory() as db:
                barrier.wait()
                claimed = JobRepository(db).claim_next(
                    lease_owner=owner,
                    now=utc_now(),
                    lease_seconds=30,
                )
                db.commit()
                return claimed.id if claimed is not None else None

        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed_ids = list(
                executor.map(claim, ("worker-one", "worker-two"))
            )
        assert [job_id for job_id in claimed_ids if job_id] == [queued.id]
    finally:
        engine.dispose()


def test_reaper_only_returns_expired_leases(tmp_path: Path) -> None:
    _, engine, session_factory = _database(tmp_path)
    try:
        expired = _job(status=JobStatus.RUNNING, lease_delta=-1)
        live = _job(status=JobStatus.RUNNING, lease_delta=60)
        with session_factory() as db:
            db.add_all((expired, live))
            db.commit()
            assert [job.id for job in JobRepository(db).expired(utc_now())] == [
                expired.id
            ]
    finally:
        engine.dispose()


def test_business_recovery_never_requeues_after_attempt_limit(
    tmp_path: Path,
) -> None:
    settings, engine, session_factory = _database(tmp_path)
    runtime = RuntimeCoordinator(settings)
    try:
        exhausted = _job(status=JobStatus.RUNNING, lease_delta=-1)
        exhausted.job_type = JobType.RAG_EVALUATION.value
        exhausted.attempt = 2
        exhausted.max_attempts = 2
        exhausted.payload = {"case_count": 0}
        exhausted.budget_total_calls = 0
        with session_factory() as db:
            db.add(exhausted)
            db.commit()
            disposition = JobRecoveryService(
                db, settings, runtime
            ).recover_expired(exhausted)
            assert disposition is RecoveryDisposition.FAILED
            assert exhausted.status == JobStatus.FAILED.value
            assert (
                exhausted.error_code
                == "RECOVERY_RETRY_ATTEMPTS_EXHAUSTED"
            )
    finally:
        runtime.close()
        engine.dispose()


def test_evaluation_recovery_recognizes_atomic_report_before_db_commit(
    tmp_path: Path,
) -> None:
    settings, engine, session_factory = _database(tmp_path)
    runtime = RuntimeCoordinator(settings)
    try:
        report_path = settings.EVALUATION_DIR / "reports" / "complete.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with session_factory() as db:
            job = JobService(db).submit(
                job_type=JobType.RAG_EVALUATION,
                created_by_id=None,
                resource_type="KNOWLEDGE_BASE",
                resource_id="44444444-4444-4444-4444-444444444444",
                payload={
                    "case_count": 0,
                    "report_path": str(report_path),
                },
                collection_name="kb44444444444444444444444444444444_g000001_deadbeef",
                embedding_config_hash="a" * 64,
                dataset_sha256="b" * 64,
                evaluation_config_hash="c" * 64,
                run_after_seconds=3600,
                max_attempts=2,
            )
            job.status = JobStatus.RUNNING.value
            job.attempt = 1
            job.lease_owner = "dead-evaluation-worker"
            job.lease_expires_at = utc_now() - timedelta(seconds=1)
            db.commit()
            payload = {
                "format": "local-rag-evaluation-report",
                "format_version": 1,
                "job_id": job.id,
                "dataset_sha256": job.dataset_sha256,
                "knowledge_base_id": job.resource_id,
                "collection_name": job.collection_name,
                "embedding_config_hash": job.embedding_config_hash,
                "evaluation_config_hash": job.evaluation_config_hash,
                "case_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "cases": [],
            }
            raw = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            report_path.write_bytes(raw)

            disposition = JobRecoveryService(
                db, settings, runtime
            ).recover_expired(job)
            assert disposition is RecoveryDisposition.SUCCEEDED
            assert job.report_path == str(report_path.resolve())
            assert job.report_sha256 == hashlib.sha256(raw).hexdigest()
    finally:
        runtime.close()
        engine.dispose()


def test_control_plane_heartbeat_renews_lease_during_long_work(
    tmp_path: Path,
) -> None:
    settings = make_test_settings(
        tmp_path,
        JOB_HEARTBEAT_SECONDS=1,
        JOB_LEASE_SECONDS=5,
    )
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    engine, session_factory = init_database(settings.DATABASE_URL)
    try:
        running = _job(status=JobStatus.RUNNING, lease_delta=2)
        running.lease_owner = "heartbeat-worker"
        original_expiry = running.lease_expires_at
        with session_factory() as db:
            db.add(running)
            db.commit()
        context = JobExecutionContext(
            job_id=running.id,
            lease_owner="heartbeat-worker",
            session_factory=session_factory,
            settings=settings,
        )
        context.start_heartbeat()
        try:
            time.sleep(1.2)
        finally:
            context.stop_heartbeat()
        with session_factory() as db:
            renewed = db.get(Job, running.id)
            assert renewed is not None
            assert renewed.lease_expires_at > original_expiry
    finally:
        engine.dispose()


def test_checkpoint_throttles_same_stage_but_persists_stage_change(
    tmp_path: Path,
) -> None:
    settings = make_test_settings(
        tmp_path,
        JOB_PROGRESS_MIN_INTERVAL_SECONDS=60,
    )
    settings.ensure_directories()
    upgrade_database(settings.DATABASE_URL)
    engine, session_factory = init_database(settings.DATABASE_URL)
    try:
        running = _job(status=JobStatus.RUNNING, lease_delta=30)
        running.lease_owner = "progress-worker"
        with session_factory() as db:
            db.add(running)
            db.commit()
        context = JobExecutionContext(
            job_id=running.id,
            lease_owner="progress-worker",
            session_factory=session_factory,
            settings=settings,
        )
        context.checkpoint("SAME_STAGE", 10, force=True)
        with session_factory() as db:
            first = db.get(Job, running.id)
            first_heartbeat = first.last_heartbeat_at
        context.checkpoint("SAME_STAGE", 11)
        with session_factory() as db:
            throttled = db.get(Job, running.id)
            assert throttled.progress == 10
            assert throttled.last_heartbeat_at == first_heartbeat
        context.checkpoint("NEW_STAGE", 11)
        with session_factory() as db:
            changed = db.get(Job, running.id)
            assert changed.progress == 11
            assert changed.stage == "NEW_STAGE"
            assert changed.last_heartbeat_at >= first_heartbeat
    finally:
        engine.dispose()


def test_second_instance_lock_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "data" / ".instance.lock"
    first = InstanceLock(path).acquire()
    try:
        with pytest.raises(InstanceLockError):
            InstanceLock(path).acquire()
    finally:
        first.release()


def test_backup_lease_expiry_never_requeues_and_clears_draining(
    tmp_path: Path,
) -> None:
    settings, engine, session_factory = _database(tmp_path)
    runtime = RuntimeCoordinator(settings)
    partial = settings.BACKUP_DIR / "backup.partial"
    partial.write_bytes(b"incomplete")
    try:
        with session_factory() as db:
            job = _job(status=JobStatus.RUNNING, lease_delta=-1)
            job.payload = {"partial_path": str(partial)}
            db.add(job)
            db.flush()
            db.add(
                RuntimeState(
                    key="BACKUP_DRAINING",
                    value={"status": "DRAINING"},
                    owner_job_id=job.id,
                    lease_expires_at=None,
                    updated_at=utc_now(),
                )
            )
            db.commit()

            disposition = JobRecoveryService(
                db, settings, runtime
            ).recover_expired(job)
            assert disposition is RecoveryDisposition.FAILED
            assert job.status == JobStatus.FAILED.value
            assert job.error_code == "BACKUP_LEASE_EXPIRED_NOT_RESUMED"
            assert db.get(RuntimeState, "BACKUP_DRAINING") is None
            assert not partial.exists()
            assert partial.with_name(
                f"{partial.name}.abandoned-{job.id}"
            ).is_file()
    finally:
        runtime.close()
        engine.dispose()


def test_queued_backup_cancel_clears_draining_and_retry_uses_new_target(
    tmp_path: Path,
) -> None:
    settings, engine, session_factory = _database(tmp_path)
    try:
        output = settings.BACKUP_DIR / "original.zip"
        with session_factory() as db:
            service = JobService(db)
            original = service.submit(
                job_type=JobType.BACKUP,
                created_by_id=None,
                resource_type="SYSTEM",
                payload={
                    "output_path": str(output),
                    "partial_path": str(output) + ".partial",
                },
            )
            service.cancel(original.id)
            assert db.get(RuntimeState, "BACKUP_DRAINING") is None

            retried = service.manual_retry(original.id, None)
            assert retried.retry_of_job_id == original.id
            assert retried.payload["output_path"] != str(output)
            assert retried.payload["partial_path"].endswith(".partial")
            assert db.get(RuntimeState, "BACKUP_DRAINING").owner_job_id == retried.id
            service.cancel(retried.id)
            assert db.get(RuntimeState, "BACKUP_DRAINING") is None
    finally:
        engine.dispose()


def test_running_backup_terminal_cleanup_clears_draining(
    tmp_path: Path,
) -> None:
    settings, engine, session_factory = _database(tmp_path)
    runtime = RuntimeCoordinator(settings)
    try:
        with session_factory() as db:
            output = settings.BACKUP_DIR / "running-backup.zip"
            job = JobService(db).submit(
                job_type=JobType.BACKUP,
                created_by_id=None,
                resource_type="SYSTEM",
                payload={
                    "output_path": str(output),
                    "partial_path": f"{output}.partial",
                },
            )
            job.status = JobStatus.RUNNING.value
            job.lease_owner = "terminal-cleanup-worker"
            job.lease_expires_at = utc_now() + timedelta(seconds=30)
            db.commit()
        worker = JobWorker(
            session_factory=session_factory,
            settings=settings,
            runtime=runtime,
        )
        worker.lease_owner = "terminal-cleanup-worker"
        worker._finish(
            job.id,
            JobStatus.CANCELLED,
            error_code="CANCELLED_AT_CHECKPOINT",
        )
        with session_factory() as db:
            assert db.get(RuntimeState, "BACKUP_DRAINING") is None
    finally:
        runtime.close()
        engine.dispose()


def test_password_policy_accepts_eight_characters_and_rejects_seven(client) -> None:
    accepted_passwords = ("12345678", "密码安全测试通过")
    for index, password in enumerate(accepted_passwords):
        username = f"eight-character-user-{index}"
        registered = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": password,
            },
        )
        assert registered.status_code == 201, registered.text
        logged_in = client.post(
            "/api/auth/login",
            json={"identity": username, "password": password},
        )
        assert logged_in.status_code == 200, logged_in.text

    too_short = client.post(
        "/api/auth/register",
        json={
            "username": "seven-character-user",
            "email": "seven-character-user@example.com",
            "password": "1234567",
        },
    )
    assert too_short.status_code == 400
    assert "密码必须至少包含 8 个字符" in too_short.text


def test_password_whitespace_is_preserved_between_register_and_login(client) -> None:
    password = " pass1234 "
    registered = client.post(
        "/api/auth/register",
        json={
            "username": "space-password-user",
            "email": " space-password@example.com ",
            "password": password,
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["data"]["email"] == "space-password@example.com"

    exact = client.post(
        "/api/auth/login",
        json={"identity": " space-password-user ", "password": password},
    )
    assert exact.status_code == 200, exact.text
    trimmed = client.post(
        "/api/auth/login",
        json={"identity": "space-password-user", "password": "pass1234"},
    )
    assert trimmed.status_code == 401


def test_username_and_email_share_one_global_login_namespace(client) -> None:
    first = client.post(
        "/api/auth/register",
        json={
            "username": "shared@example.com",
            "email": "first@example.com",
            "password": "password-one",
        },
    )
    assert first.status_code == 201, first.text

    email_collision = client.post(
        "/api/auth/register",
        json={
            "username": "second-user",
            "email": "SHARED@example.com",
            "password": "password-two",
        },
    )
    assert email_collision.status_code == 409

    username_collision = client.post(
        "/api/auth/register",
        json={
            "username": "FIRST@example.com",
            "email": "third@example.com",
            "password": "password-three",
        },
    )
    assert username_collision.status_code == 409

    same_identity = client.post(
        "/api/auth/register",
        json={
            "username": "same@example.com",
            "email": "same@example.com",
            "password": "password-four",
        },
    )
    assert same_identity.status_code == 201, same_identity.text
    login = client.post(
        "/api/auth/login",
        json={"identity": "SAME@example.com", "password": "password-four"},
    )
    assert login.status_code == 200, login.text


def test_concurrent_registration_cannot_claim_one_identity_twice(client) -> None:
    def register(index: int) -> int:
        response = client.post(
            "/api/auth/register",
            json={
                "username": f"concurrent-user-{index}",
                "email": "one-concurrent-identity@example.com",
                "password": "password-eight",
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(register, (1, 2)))
    assert statuses == [201, 409]


def test_identity_normalization_password_boundary_and_live_user_reload(
    client,
    app,
) -> None:
    password_72 = "p" * 72
    registered = client.post(
        "/api/auth/register",
        json={
            "username": "Alice",
            "email": "Alice@Example.COM",
            "password": password_72,
        },
    )
    assert registered.status_code == 201

    duplicate = client.post(
        "/api/auth/register",
        json={
            "username": "Ａｌｉｃｅ",
            "email": "different@example.com",
            "password": "another-password",
        },
    )
    assert duplicate.status_code == 409
    too_long = client.post(
        "/api/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "p" * 73,
        },
    )
    assert too_long.status_code == 400

    login = client.post(
        "/api/auth/login",
        json={"identity": "ａｌｉｃｅ＠ｅｘａｍｐｌｅ．ｃｏｍ", "password": password_72},
    )
    assert login.status_code == 200
    alice_token = login.json()["data"]["access_token"]
    alice_id = login.json()["data"]["user"]["id"]

    with app.state.session_factory() as db:
        alice = db.get(User, alice_id)
        assert alice is not None
        alice.role = UserRole.ADMIN.value
        db.commit()
    refreshed = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["role"] == UserRole.ADMIN.value

    with app.state.session_factory() as db:
        alice = db.get(User, alice_id)
        assert alice is not None
        alice.is_active = False
        db.commit()
    disabled = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert disabled.status_code == 401


def test_metrics_requires_its_own_scrape_token(client) -> None:
    missing = client.get("/metrics")
    assert missing.status_code == 422
    wrong = client.get(
        "/metrics", headers={"X-Metrics-Scrape-Token": "wrong"}
    )
    assert wrong.status_code == 401
    scraped = client.get(
        "/metrics",
        headers={"X-Metrics-Scrape-Token": "test-metrics-token"},
    )
    assert scraped.status_code == 200
    assert "local_rag_nonterminal_jobs" in scraped.text
    assert "local_rag_http_requests_total" in scraped.text
    assert "local_rag_jobs_terminal_total" in scraped.text
    assert "local_rag_embedding_errors_total" in scraped.text
    assert "local_rag_retrieval_duration_seconds" in scraped.text

"""Signed logical backup round-trip and hostile ZIP preflight tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
import sys
from datetime import datetime, timedelta, timezone
import warnings
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ValidationException
from app.core.instance_lock import InstanceLockError
from app.services.backup_restore_service import BackupRestoreService
from app.services.backup_service import canonical_json
from app.services.vector_store_service import VectorStoreService
from scripts import backup as backup_cli
from tests.conftest import make_test_settings, wait_for_job
from tests.fakes import FakeEmbedding


def _write_zip(
    path: Path,
    members: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, payload in members:
                archive.writestr(name, payload)


@pytest.mark.parametrize(
    "members",
    [
        [("../escape", b"x")],
        [("A.txt", b"a"), ("a.txt", b"b")],
        [("Ａ.txt", b"a"), ("a.txt", b"b")],
        [("same.txt", b"a"), ("same.txt", b"b")],
        [(r"C:\escape.txt", b"x")],
    ],
)
def test_zip_preflight_rejects_paths_duplicates_and_windows_collisions(
    tmp_path: Path,
    members: list[tuple[str | zipfile.ZipInfo, bytes]],
) -> None:
    settings = make_test_settings(tmp_path)
    archive_path = tmp_path / "hostile.zip"
    _write_zip(archive_path, members)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValidationException):
            BackupRestoreService(settings)._preflight(archive)


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO])
def test_zip_preflight_rejects_symlinks_and_non_regular_members(
    tmp_path: Path,
    mode: int,
) -> None:
    settings = make_test_settings(tmp_path)
    archive_path = tmp_path / "special.zip"
    info = zipfile.ZipInfo("special")
    info.create_system = 3
    info.external_attr = (mode | 0o777) << 16
    _write_zip(archive_path, [(info, b"target")])
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValidationException):
            BackupRestoreService(settings)._preflight(archive)


def test_zip_preflight_rejects_zip_bomb_ratio(tmp_path: Path) -> None:
    settings = make_test_settings(
        tmp_path, BACKUP_MAX_COMPRESSION_RATIO=2.0
    )
    archive_path = tmp_path / "ratio.zip"
    _write_zip(archive_path, [("huge.txt", b"0" * 100_000)])
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValidationException, match="压缩比"):
            BackupRestoreService(settings)._preflight(archive)


@pytest.mark.parametrize(
    ("setting_overrides", "members", "message"),
    [
        (
            {"BACKUP_MAX_MEMBERS": 1},
            [("one", b"1"), ("two", b"2"), ("three", b"3")],
            "成员数",
        ),
        (
            {"BACKUP_MAX_MEMBER_BYTES": 4},
            [("large", b"12345")],
            "单成员",
        ),
        (
            {
                "BACKUP_MAX_MEMBER_BYTES": 10,
                "BACKUP_MAX_TOTAL_BYTES": 5,
            },
            [("one", b"123"), ("two", b"456")],
            "总解压大小",
        ),
    ],
)
def test_zip_preflight_rejects_member_resource_limits(
    tmp_path: Path,
    setting_overrides: dict[str, int],
    members: list[tuple[str, bytes]],
    message: str,
) -> None:
    settings = make_test_settings(tmp_path, **setting_overrides)
    archive_path = tmp_path / "resource-limit.zip"
    _write_zip(archive_path, members, compression=zipfile.ZIP_STORED)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValidationException, match=message):
            BackupRestoreService(settings)._preflight(archive)


def test_zip_preflight_rejects_untrusted_manifest_hmac(
    tmp_path: Path,
) -> None:
    settings = make_test_settings(tmp_path)
    archive_path = tmp_path / "bad-signature.zip"
    manifest = {
        "format": "local-rag-online-logical-backup",
        "format_version": 1,
        "backup_type": "online-logical",
        "members": [],
        "collections": [],
        "pointers": [],
        "hmac_sha256": "0" * 64,
    }
    _write_zip(
        archive_path,
        [
            (
                "manifest.json",
                json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
            )
        ],
    )
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValidationException, match="HMAC"):
            BackupRestoreService(settings)._preflight(archive)


def test_restore_rejects_member_hash_even_with_valid_manifest_hmac(
    tmp_path: Path,
) -> None:
    settings = make_test_settings(tmp_path)
    signing_key = settings.BACKUP_SIGNING_KEY.get_secret_value()
    expected_payload = b"expected"
    actual_payload = b"tampered"
    unsigned = {
        "format": "local-rag-online-logical-backup",
        "format_version": 1,
        "backup_type": "online-logical",
        "members": [
            {
                "name": "payload.bin",
                "size": len(actual_payload),
                "sha256": hashlib.sha256(expected_payload).hexdigest(),
            }
        ],
        "collections": [],
        "pointers": [],
    }
    manifest = {
        **unsigned,
        "hmac_sha256": hmac.new(
            signing_key.encode("utf-8"),
            canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest(),
    }
    archive_path = tmp_path / "signed-corrupt-member.zip"
    _write_zip(
        archive_path,
        [
            ("payload.bin", actual_payload),
            ("manifest.json", canonical_json(manifest)),
        ],
        compression=zipfile.ZIP_STORED,
    )

    with pytest.raises(ValidationException, match="成员哈希"):
        BackupRestoreService(settings).restore(
            archive_path, tmp_path / "signed-corrupt-restore"
        )


def test_backup_retention_dry_run_and_single_explicit_delete(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    old_archive = tmp_path / "old.zip"
    recent_archive = tmp_path / "recent.zip"
    old_archive.write_bytes(b"old")
    recent_archive.write_bytes(b"recent")
    old_timestamp = (
        datetime.now(timezone.utc) - timedelta(days=40)
    ).timestamp()
    os.utime(old_archive, (old_timestamp, old_timestamp))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup.py",
            "retention",
            "--directory",
            str(tmp_path),
            "--older-than-days",
            "30",
        ],
    )
    assert backup_cli.main() == 0
    dry_run = capsys.readouterr().out
    assert str(old_archive.resolve()) in dry_run
    assert str(recent_archive.resolve()) not in dry_run
    assert old_archive.is_file()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup.py",
            "retention",
            "--directory",
            str(tmp_path),
            "--older-than-days",
            "30",
            "--delete-one",
            str(old_archive),
        ],
    )
    assert backup_cli.main() == 0
    assert not old_archive.exists()
    assert recent_archive.is_file()


def test_online_logical_backup_is_offline_restorable_and_scrubs_itself(
    app,
    test_settings,
    tmp_path: Path,
) -> None:
    archive_path: Path
    target = tmp_path / "restored-logical-backup"
    with TestClient(app, raise_server_exceptions=False) as client:
        bootstrap = client.post(
            "/api/auth/bootstrap",
            headers={"X-Bootstrap-Secret": "test-bootstrap-secret"},
            json={
                "username": "backup-admin",
                "email": "backup-admin@example.com",
                "password": "backup-password-123",
            },
        )
        assert bootstrap.status_code == 200
        login = client.post(
            "/api/auth/login",
            json={
                "identity": "backup-admin",
                "password": "backup-password-123",
            },
        )
        token = login.json()["data"]["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        fake = FakeEmbedding()
        app.state.rag_runtime.vector_store._embedding_factory = lambda _: fake
        app.state.rag_runtime.vector_store._embedding_cache.clear()
        knowledge_base_id = client.post(
            "/api/knowledge-bases", json={"name": "backup-content"}
        ).json()["data"]["id"]
        uploaded = client.post(
            "/api/files/upload",
            data={"knowledge_base_id": knowledge_base_id},
            files={
                "file": (
                    "backup.txt",
                    b"logical backup vector",
                    "text/plain",
                )
            },
        ).json()["data"]
        assert wait_for_job(
            client, client.post(f"/api/files/{uploaded['id']}/process")
        )["status"] == "SUCCEEDED"
        backup_job = wait_for_job(client, client.post("/api/backups"))
        assert backup_job["status"] == "SUCCEEDED"
        archive_path = Path(backup_job["result"]["backup_path"])
        assert archive_path.is_file()
        with pytest.raises(InstanceLockError):
            BackupRestoreService(test_settings).restore(
                archive_path, target
            )

    restored = BackupRestoreService(test_settings).restore(
        archive_path, target
    )
    assert restored == target
    restored_database = target / "metadata" / "local_rag_chat.db"
    with sqlite3.connect(restored_database) as connection:
        backup_rows = connection.execute(
            """
            SELECT status, error_code, lease_owner, lease_expires_at
            FROM jobs WHERE job_type='BACKUP'
            """
        ).fetchall()
        assert backup_rows == [
            (
                "FAILED",
                "RESTORED_BACKUP_NOT_RESUMED",
                None,
                None,
            )
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM runtime_state"
        ).fetchone()[0] == 0
        collection_name = connection.execute(
            "SELECT active_collection_name FROM knowledge_bases "
            "WHERE name='backup-content'"
        ).fetchone()[0]
    restored_settings = test_settings.model_copy(
        update={"CHROMA_DIR": target / "chroma"}
    )
    vector_store = VectorStoreService(restored_settings)
    try:
        assert len(
            vector_store.snapshot_collection(collection_name).vectors.ids
        ) == 1
    finally:
        client = vector_store._client
        system = getattr(client, "_system", None)
        stop = getattr(system, "stop", None)
        if callable(stop):
            stop()

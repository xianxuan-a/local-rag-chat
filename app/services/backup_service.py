"""Online logical backup under the global exclusive business-write barrier."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConfigurationException, ConflictException
from app.core.logger import get_logger
from app.models import (
    FileRecord,
    FileStatus,
    Job,
    JobStatus,
    KnowledgeBase,
    NON_TERMINAL_JOB_STATUSES,
    RebuildStatus,
    RuntimeState,
)
from app.services.runtime_coordinator import RuntimeCoordinator


BUFFER_SIZE = 1024 * 1024
FORMAT_VERSION = 1
logger = get_logger(__name__)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def canonical_collection_bytes(snapshot: object) -> bytes:
    vectors = snapshot.vectors
    rows = sorted(
        zip(
            vectors.ids,
            vectors.documents,
            vectors.metadatas,
            vectors.embeddings,
            strict=True,
        ),
        key=lambda row: row[0],
    )
    return canonical_json(
        {
            "name": snapshot.name,
            "metadata": snapshot.metadata,
            "configuration": snapshot.configuration,
            "ids": [row[0] for row in rows],
            "documents": [row[1] for row in rows],
            "metadatas": [row[2] for row in rows],
            "embeddings": [row[3] for row in rows],
        }
    )


class OnlineBackupService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        runtime: RuntimeCoordinator,
    ) -> None:
        self.db = db
        self.settings = settings
        self.runtime = runtime

    def run(self, job: Job, checkpoint: object) -> dict[str, Any]:
        signing_key = self.settings.BACKUP_SIGNING_KEY.get_secret_value()
        if not signing_key:
            raise ConfigurationException("BACKUP_SIGNING_KEY 未配置")
        output = Path(str(job.payload["output_path"])).resolve()
        partial = Path(str(job.payload["partial_path"])).resolve()
        snapshot_path = output.with_name(f".{output.name}.sqlite-snapshot")
        if output.exists() or partial.exists() or snapshot_path.exists():
            raise ConflictException("备份目标或临时文件已存在，拒绝覆盖")
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self.runtime.backup_exclusive():
                checkpoint("BACKUP_EXCLUSIVE_BARRIER", 10, force=True)
                self._validate_quiescent(job.id)
                pointers = self._fixed_pointers()
                self._sqlite_snapshot(snapshot_path)
                self._scrub_snapshot(snapshot_path, job.id)
                checkpoint("BACKUP_SQLITE_SNAPSHOT", 30, force=True)

                members: list[dict[str, object]] = []
                with zipfile.ZipFile(
                    partial,
                    "x",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                    allowZip64=True,
                ) as archive:
                    self._add_file(
                        archive,
                        snapshot_path,
                        "metadata/local_rag_chat.db",
                        members,
                    )
                    collection_summaries: list[dict[str, object]] = []
                    for index, (name, expected_hash) in enumerate(pointers):
                        snapshot = self.runtime.vector_store.snapshot_collection(name)
                        actual_hash = snapshot.metadata.get(
                            "embedding_config_hash"
                        )
                        if expected_hash and actual_hash != expected_hash:
                            raise ConflictException(
                                f"Collection 配置哈希与固定指针不一致：{name}"
                            )
                        payload = canonical_collection_bytes(snapshot)
                        member_name = (
                            f"logical_chroma/collections/{index:05d}.json"
                        )
                        self._add_bytes(archive, payload, member_name, members)
                        collection_summaries.append(
                            {
                                "name": name,
                                "member": member_name,
                                "count": len(snapshot.vectors.ids),
                                "embedding_config_hash": actual_hash,
                                "content_sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        )
                    checkpoint("BACKUP_CHROMA_LOGICAL_EXPORT", 65, force=True)

                    for path, member_name in self._iter_upload_members():
                        self._add_file(archive, path, member_name, members)
                    for path, member_name in self._iter_evaluation_members():
                        self._add_file(archive, path, member_name, members)
                    config_summary = {
                        "app_version": self.settings.APP_VERSION,
                        "embedding_provider": self.settings.EMBEDDING_PROVIDER,
                        "embedding_model": self.settings.EMBEDDING_MODEL,
                        "embedding_dimension": self.settings.EMBEDDING_DIMENSION,
                        "chunk_size": self.settings.CHUNK_SIZE,
                        "chunk_overlap": self.settings.CHUNK_OVERLAP,
                    }
                    self._add_bytes(
                        archive,
                        canonical_json(config_summary),
                        "config/summary.json",
                        members,
                    )
                    unsigned_manifest = {
                        "format": "local-rag-online-logical-backup",
                        "format_version": FORMAT_VERSION,
                        "backup_type": "online-logical",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "cross_store_transaction": False,
                        "sqlite_consistency": "sqlite-backup-api",
                        "database_jobs_scrubbed": True,
                        "pointers": [
                            {
                                "collection_name": name,
                                "embedding_config_hash": config_hash,
                            }
                            for name, config_hash in pointers
                        ],
                        "collections": collection_summaries,
                        "members": members,
                    }
                    signature = hmac.new(
                        signing_key.encode("utf-8"),
                        canonical_json(unsigned_manifest),
                        hashlib.sha256,
                    ).hexdigest()
                    manifest = {
                        **unsigned_manifest,
                        "hmac_sha256": signature,
                    }
                    archive.writestr("manifest.json", canonical_json(manifest))
                os.replace(partial, output)
        finally:
            if snapshot_path.exists():
                snapshot_path.unlink()
            if partial.is_file():
                quarantine = partial.with_name(
                    f"{partial.name}.abandoned-{job.id}"
                )
                if quarantine.exists():
                    logger.critical(
                        "备份失败且 partial 隔离目标已存在（job_id=%s, partial=%s）",
                        job.id,
                        partial,
                    )
                else:
                    os.replace(partial, quarantine)
            state = self.db.get(RuntimeState, "BACKUP_DRAINING")
            if state is not None and state.owner_job_id == job.id:
                self.db.delete(state)
                self.db.commit()
        return {
            "backup_path": str(output),
            "backup_type": "online-logical",
            "sha256": sha256_file(output),
        }

    def _validate_quiescent(self, backup_job_id: str) -> None:
        other = self.db.scalar(
            select(Job.id).where(
                Job.id != backup_job_id,
                Job.status.in_(NON_TERMINAL_JOB_STATUSES),
            )
        )
        if other:
            raise ConflictException("备份独占阶段发现其他非终态 Job")
        if self.db.scalar(
            select(FileRecord.id).where(
                FileRecord.status == FileStatus.PROCESSING
            )
        ):
            raise ConflictException("存在 PROCESSING 文件，拒绝备份")
        if self.db.scalar(
            select(KnowledgeBase.id).where(
                KnowledgeBase.rebuild_status == RebuildStatus.BUILDING
            )
        ):
            raise ConflictException("存在 BUILDING 知识库，拒绝备份")

    def _fixed_pointers(self) -> list[tuple[str, str | None]]:
        pointers: dict[str, str | None] = {}
        for knowledge_base in self.db.scalars(select(KnowledgeBase)).all():
            for name, config_hash in (
                (
                    knowledge_base.active_collection_name,
                    knowledge_base.active_embedding_config_hash,
                ),
                (
                    knowledge_base.previous_collection_name,
                    knowledge_base.previous_embedding_config_hash,
                ),
                (
                    knowledge_base.cleanup_collection_name,
                    None,
                ),
            ):
                if not name:
                    continue
                existing = pointers.get(name)
                if existing and config_hash and existing != config_hash:
                    raise ConflictException("Collection 指针配置哈希互相冲突")
                pointers[name] = existing or config_hash
        return sorted(pointers.items())

    def _sqlite_snapshot(self, target: Path) -> None:
        database_path = Path(
            self.db.get_bind().url.database or ""
        ).expanduser().resolve()
        with closing(sqlite3.connect(database_path)) as source:
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
                check = destination.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise ConflictException("SQLite 备份快照完整性检查失败")

    @staticmethod
    def _scrub_snapshot(path: Path, backup_job_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status='FAILED',
                    error_code=CASE
                        WHEN id=? THEN 'RESTORED_BACKUP_NOT_RESUMED'
                        ELSE 'RESTORED_NON_TERMINAL'
                    END,
                    error_message='Snapshot restore does not resume non-terminal jobs',
                    lease_owner=NULL,
                    lease_expires_at=NULL,
                    last_heartbeat_at=NULL,
                    finished_at=?,
                    updated_at=?
                WHERE status IN ('QUEUED','RUNNING','CANCEL_REQUESTED')
                """,
                (backup_job_id, now, now),
            )
            connection.execute(
                """
                UPDATE file_records
                SET status='FAILED',
                    error_message='RESTORED_RETRY_REQUIRED',
                    processing_job_id=NULL,
                    updated_at=?
                WHERE status='PROCESSING'
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE knowledge_bases
                SET rebuild_status='FAILED', updated_at=?
                WHERE rebuild_status='BUILDING'
                """,
                (now,),
            )
            connection.execute("DELETE FROM runtime_state")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ConflictException(
                    f"快照清理后外键检查失败：{violations}"
                )
            connection.commit()

    def _iter_upload_members(self) -> Iterable[tuple[Path, str]]:
        root = self.settings.UPLOAD_DIR.resolve()
        if not root.exists():
            return
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise ConflictException(f"上传目录包含符号链接：{path}")
            if path.is_file():
                yield path, f"uploads/{path.relative_to(root).as_posix()}"

    def _iter_evaluation_members(self) -> Iterable[tuple[Path, str]]:
        root = self.settings.EVALUATION_DIR.resolve()
        if not root.exists():
            return
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise ConflictException(f"评估目录包含符号链接：{path}")
            if path.is_file():
                yield path, f"evaluations/{path.relative_to(root).as_posix()}"

    @staticmethod
    def _add_file(
        archive: zipfile.ZipFile,
        path: Path,
        member_name: str,
        members: list[dict[str, object]],
    ) -> None:
        archive.write(path, member_name)
        members.append(
            {
                "name": member_name,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    @staticmethod
    def _add_bytes(
        archive: zipfile.ZipFile,
        payload: bytes,
        member_name: str,
        members: list[dict[str, object]],
    ) -> None:
        archive.writestr(member_name, payload)
        members.append(
            {
                "name": member_name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

"""Strict offline restoration of signed online logical backup archives."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import unicodedata
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.core.exceptions import ConfigurationException, ValidationException
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.services.backup_service import (
    canonical_collection_bytes,
    canonical_json,
)
from app.services.vector_store_service import (
    CollectionSnapshot,
    VectorSnapshot,
    VectorStoreService,
)


WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class BackupRestoreService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def restore(self, archive_path: Path, target: Path) -> Path:
        archive_path = archive_path.expanduser().resolve()
        target = target.expanduser().resolve()
        if not archive_path.is_file():
            raise FileNotFoundError(f"备份归档不存在：{archive_path}")
        if target.exists():
            raise FileExistsError(f"恢复目标已存在，拒绝覆盖：{target}")
        live_paths = {
            self.settings.DATA_DIR.resolve(),
            self.settings.CHROMA_DIR.resolve(),
            self.settings.UPLOAD_DIR.resolve(),
            self.settings.METADATA_DIR.resolve(),
        }
        if target in live_paths:
            raise ValidationException("恢复目标不能是任何 live 数据目录")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.staging-{uuid4().hex}")
        if staging.exists():
            raise FileExistsError(f"恢复 staging 已存在：{staging}")

        with InstanceLock(instance_lock_path(self.settings.DATA_DIR)):
            with zipfile.ZipFile(archive_path, "r") as archive:
                manifest, member_infos = self._preflight(archive)
                staging.mkdir(parents=False, exist_ok=False)
                self._extract_members(
                    archive, member_infos, manifest, staging
                )
            self._scrub_restored_database(
                staging / "metadata" / "local_rag_chat.db"
            )
            self._import_collections(staging, manifest)
            self._validate_database_pointers(staging, manifest)
            (staging / "restore_manifest.json").write_bytes(
                canonical_json(manifest)
            )
            os.replace(staging, target)
        return target

    def _preflight(
        self, archive: zipfile.ZipFile
    ) -> tuple[dict[str, Any], dict[str, zipfile.ZipInfo]]:
        infos = archive.infolist()
        if len(infos) > self.settings.BACKUP_MAX_MEMBERS + 1:
            raise ValidationException("归档成员数超过限制")
        exact_names: set[str] = set()
        windows_names: set[str] = set()
        member_infos: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            name = info.filename
            if name in exact_names:
                raise ValidationException(f"归档包含重复成员名：{name}")
            exact_names.add(name)
            normalized_key = self._validate_member_name(name)
            if normalized_key in windows_names:
                raise ValidationException(
                    f"归档包含 Unicode/Windows 大小写冲突：{name}"
                )
            windows_names.add(normalized_key)
            self._validate_member_type(info)
            if info.file_size > self.settings.BACKUP_MAX_MEMBER_BYTES:
                raise ValidationException(f"归档单成员超过限制：{name}")
            total_size += info.file_size
            if total_size > self.settings.BACKUP_MAX_TOTAL_BYTES:
                raise ValidationException("归档总解压大小超过限制")
            if (
                info.file_size
                and info.file_size / max(1, info.compress_size)
                > self.settings.BACKUP_MAX_COMPRESSION_RATIO
            ):
                raise ValidationException(f"归档压缩比异常：{name}")
            if not info.is_dir():
                member_infos[name] = info
        manifest_info = member_infos.get("manifest.json")
        if manifest_info is None or manifest_info.file_size > 5 * 1024 * 1024:
            raise ValidationException("Manifest 缺失或过大")
        try:
            manifest = json.loads(archive.read(manifest_info))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationException("Manifest 不是有效 UTF-8 JSON") from exc
        self._verify_manifest(manifest, member_infos)
        return manifest, member_infos

    def _verify_manifest(
        self,
        manifest: object,
        member_infos: dict[str, zipfile.ZipInfo],
    ) -> None:
        if not isinstance(manifest, dict):
            raise ValidationException("Manifest 必须是对象")
        if (
            manifest.get("format") != "local-rag-online-logical-backup"
            or manifest.get("format_version") != 1
            or manifest.get("backup_type") != "online-logical"
        ):
            raise ValidationException("不支持的备份格式或版本")
        signature = manifest.get("hmac_sha256")
        if not isinstance(signature, str):
            raise ValidationException("Manifest HMAC 缺失")
        signing_key = self.settings.BACKUP_SIGNING_KEY.get_secret_value()
        if not signing_key:
            raise ConfigurationException("BACKUP_SIGNING_KEY 未配置")
        unsigned = dict(manifest)
        unsigned.pop("hmac_sha256", None)
        expected = hmac.new(
            signing_key.encode("utf-8"),
            canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValidationException("Manifest HMAC 验证失败，归档来源不可信")
        members = manifest.get("members")
        if not isinstance(members, list):
            raise ValidationException("Manifest members 无效")
        declared: dict[str, dict[str, Any]] = {}
        for item in members:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("size"), int)
                or not isinstance(item.get("sha256"), str)
            ):
                raise ValidationException("Manifest 成员条目无效")
            name = item["name"]
            if name in declared:
                raise ValidationException("Manifest 包含重复成员")
            declared[name] = item
        actual = set(member_infos) - {"manifest.json"}
        if actual != set(declared):
            raise ValidationException("Manifest 成员集合与 ZIP 不一致")
        for name, item in declared.items():
            if member_infos[name].file_size != item["size"]:
                raise ValidationException(f"Manifest 成员大小不一致：{name}")

    @staticmethod
    def _validate_member_name(name: str) -> str:
        if not name or "\x00" in name or "\\" in name:
            raise ValidationException("归档成员名为空、含 NUL 或反斜杠")
        if name.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", name):
            raise ValidationException(f"归档包含绝对/盘符/UNC 路径：{name}")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValidationException(f"归档包含路径穿越：{name}")
        normalized_parts: list[str] = []
        for part in path.parts:
            normalized = unicodedata.normalize("NFKC", part)
            windows_component = normalized.rstrip(" .").casefold()
            if not windows_component or ":" in windows_component:
                raise ValidationException(f"归档成员名不兼容 Windows：{name}")
            stem = windows_component.split(".", 1)[0]
            if stem in WINDOWS_RESERVED:
                raise ValidationException(f"归档使用 Windows 保留名：{name}")
            normalized_parts.append(windows_component)
        return "/".join(normalized_parts)

    @staticmethod
    def _validate_member_type(info: zipfile.ZipInfo) -> None:
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(unix_mode)
        if stat.S_ISLNK(unix_mode):
            raise ValidationException(f"归档拒绝符号链接：{info.filename}")
        if file_type and not (
            stat.S_ISREG(unix_mode) or stat.S_ISDIR(unix_mode)
        ):
            raise ValidationException(
                f"归档拒绝硬链接或其他非普通文件：{info.filename}"
            )

    def _extract_members(
        self,
        archive: zipfile.ZipFile,
        infos: dict[str, zipfile.ZipInfo],
        manifest: dict[str, Any],
        staging: Path,
    ) -> None:
        expected = {item["name"]: item for item in manifest["members"]}
        total_written = 0
        staging_text = str(staging.resolve())
        for name, item in expected.items():
            info = infos[name]
            destination = (staging / PurePosixPath(name)).resolve()
            if os.path.commonpath((staging_text, str(destination))) != staging_text:
                raise ValidationException(f"成员目标逃逸 staging：{name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with archive.open(info, "r") as source, destination.open("xb") as sink:
                while block := source.read(1024 * 1024):
                    written += len(block)
                    total_written += len(block)
                    if (
                        written > self.settings.BACKUP_MAX_MEMBER_BYTES
                        or total_written > self.settings.BACKUP_MAX_TOTAL_BYTES
                        or written > info.file_size
                    ):
                        raise ValidationException("流式解压超过声明限制")
                    digest.update(block)
                    sink.write(block)
            if (
                written != item["size"]
                or digest.hexdigest() != item["sha256"]
            ):
                raise ValidationException(f"成员哈希验证失败：{name}")

    @staticmethod
    def _scrub_restored_database(database_path: Path) -> None:
        if not database_path.is_file():
            raise ValidationException("恢复包缺少 SQLite 数据库")
        now = "1970-01-01T00:00:00+00:00"
        with closing(sqlite3.connect(database_path)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValidationException("恢复 SQLite 完整性检查失败")
            connection.execute(
                """
                UPDATE jobs
                SET status='FAILED',
                    error_code=CASE WHEN job_type='BACKUP'
                        THEN 'RESTORED_BACKUP_NOT_RESUMED'
                        ELSE 'RESTORED_NON_TERMINAL' END,
                    error_message='Offline restore never resumes jobs',
                    lease_owner=NULL, lease_expires_at=NULL,
                    last_heartbeat_at=NULL, finished_at=COALESCE(finished_at, ?)
                WHERE status IN ('QUEUED','RUNNING','CANCEL_REQUESTED')
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE file_records
                SET status='FAILED', error_message='RESTORED_RETRY_REQUIRED',
                    processing_job_id=NULL
                WHERE status='PROCESSING'
                """
            )
            connection.execute(
                "UPDATE knowledge_bases SET rebuild_status='FAILED' "
                "WHERE rebuild_status='BUILDING'"
            )
            connection.execute("DELETE FROM runtime_state")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValidationException(
                    f"恢复 SQLite 外键检查失败：{violations}"
                )
            connection.commit()

    def _import_collections(
        self, staging: Path, manifest: dict[str, Any]
    ) -> None:
        restore_settings = self.settings.model_copy(
            update={"CHROMA_DIR": (staging / "chroma").resolve()}
        )
        vector_store = VectorStoreService(restore_settings)
        try:
            for summary in manifest.get("collections", []):
                member = staging / str(summary["member"])
                payload = json.loads(member.read_text(encoding="utf-8"))
                if payload.get("name") != summary.get("name"):
                    raise ValidationException(
                        "逻辑 Collection 名称与 Manifest 不一致"
                    )
                snapshot = CollectionSnapshot(
                    name=payload["name"],
                    metadata=payload["metadata"],
                    configuration=payload["configuration"],
                    vectors=VectorSnapshot(
                        ids=payload["ids"],
                        documents=payload["documents"],
                        metadatas=payload["metadatas"],
                        embeddings=payload["embeddings"],
                    ),
                )
                vector_store.restore_collection(snapshot)
                restored = vector_store.snapshot_collection(snapshot.name)
                if (
                    len(restored.vectors.ids) != int(summary["count"])
                    or restored.metadata.get("embedding_config_hash")
                    != summary.get("embedding_config_hash")
                    or hashlib.sha256(
                        canonical_collection_bytes(restored)
                    ).hexdigest()
                    != summary.get("content_sha256")
                ):
                    raise ValidationException(
                        f"逻辑 Collection 导入验证失败：{snapshot.name}"
                    )
        finally:
            client = vector_store._client
            system = getattr(client, "_system", None)
            stop = getattr(system, "stop", None)
            if callable(stop):
                stop()
            vector_store._client = None

    @staticmethod
    def _validate_database_pointers(
        staging: Path, manifest: dict[str, Any]
    ) -> None:
        declared = {
            item["name"]: item
            for item in manifest.get("collections", [])
        }
        database = staging / "metadata" / "local_rag_chat.db"
        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute(
                """
                SELECT active_collection_name, active_embedding_config_hash,
                       previous_collection_name, previous_embedding_config_hash,
                       cleanup_collection_name
                FROM knowledge_bases
                """
            ).fetchall()
        for active, active_hash, previous, previous_hash, cleanup in rows:
            for name, config_hash in (
                (active, active_hash),
                (previous, previous_hash),
                (cleanup, None),
            ):
                if not name:
                    continue
                summary = declared.get(name)
                if summary is None:
                    raise ValidationException(
                        f"数据库指针引用未导入 Collection：{name}"
                    )
                if (
                    config_hash
                    and summary.get("embedding_config_hash") != config_hash
                ):
                    raise ValidationException(
                        f"数据库指针配置哈希不一致：{name}"
                    )

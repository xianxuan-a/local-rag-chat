"""Migrate only verified database copies unless explicit cutover proofs are given."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.config import get_settings
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.database.migrations import (
    current_revision,
    stamp_database,
    upgrade_database,
)
from app.database.schema_contract import (
    compare_schema,
    describe_database,
    describe_metadata,
)
from app.database.sqlite_fingerprint import sqlite_logical_sha256
from app.database.sqlite import create_db_engine
from app.models import Base


LEGACY_TABLES = (
    "knowledge_bases",
    "file_records",
    "chat_sessions",
    "chat_messages",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def sqlite_backup(source: Path, target: Path) -> None:
    with closing(
        sqlite3.connect(
            f"file:{source.resolve().as_posix()}?mode=ro", uri=True
        )
    ) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)


def _row_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in LEGACY_TABLES
        }


def _assert_integrity(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if not integrity or integrity[0] != "ok" or foreign_keys:
        raise RuntimeError(
            f"数据库完整性检查失败：integrity={integrity}, foreign_keys={foreign_keys}"
        )


def migrate_copy(source: Path, target: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    if source == target:
        raise ValueError("copy-upgrade 禁止原地迁移")
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(f"目标副本已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    reference = target.with_name(f".baseline-reference-{uuid4().hex}.db")
    before_counts = _row_counts(source)
    try:
        upgrade_database(sqlite_url(reference), "0001_current_schema")
        sqlite_backup(source, target)
        actual_engine = create_db_engine(sqlite_url(target))
        reference_engine = create_db_engine(sqlite_url(reference))
        try:
            revision = current_revision(actual_engine)
            if revision not in {None, "0001_current_schema"}:
                raise RuntimeError(f"源副本 revision 不可作为 baseline：{revision}")
            differences = compare_schema(
                describe_database(reference_engine, LEGACY_TABLES),
                describe_database(actual_engine, LEGACY_TABLES),
            )
            if differences:
                raise RuntimeError(
                    "规范化 baseline 比对失败："
                    + ", ".join(item.table for item in differences)
                )
        finally:
            actual_engine.dispose()
            reference_engine.dispose()
        if revision is None:
            stamp_database(sqlite_url(target), "0001_current_schema")
        upgrade_database(sqlite_url(target), "head")

        migrated_engine = create_db_engine(sqlite_url(target))
        try:
            differences = compare_schema(
                describe_metadata(Base.metadata),
                describe_database(migrated_engine),
            )
            if differences:
                raise RuntimeError(
                    "head Schema 比对失败："
                    + ", ".join(item.table for item in differences)
                )
        finally:
            migrated_engine.dispose()
        _assert_integrity(target)
        after_counts = _row_counts(target)
        if before_counts != after_counts:
            raise RuntimeError(
                f"迁移前后历史表行数不一致：{before_counts} != {after_counts}"
            )
        return {
            "source": str(source),
            "target": str(target),
            "before_counts": before_counts,
            "after_counts": after_counts,
            "revision": "0002_auth_jobs_ownership",
        }
    finally:
        reference_wal = Path(f"{reference}-wal")
        reference_shm = Path(f"{reference}-shm")
        if reference.exists():
            reference.unlink()
        if reference_wal.exists():
            reference_wal.unlink()
        if reference_shm.exists():
            reference_shm.unlink()


def final_cutover(
    database: Path,
    pre_migration_backup: Path,
    restore_drill: Path,
) -> dict[str, object]:
    settings = get_settings()
    database = database.expanduser().resolve()
    backup = pre_migration_backup.expanduser().resolve()
    drill = restore_drill.expanduser().resolve()
    if not backup.is_file() or not drill.is_dir():
        raise RuntimeError("最终切换要求已存在迁移前备份和恢复演练目录")
    marker = drill / "pre_migration_restore_drill.json"
    if not marker.is_file():
        raise RuntimeError("恢复演练缺少验证 marker")
    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    backup_digest = sha256_file(backup)
    if (
        marker_payload.get("archive_sha256") != backup_digest
        or Path(str(marker_payload.get("archive") or "")).resolve()
        != backup
        or marker_payload.get("database_integrity") != "ok"
    ):
        raise RuntimeError("恢复演练 marker 与所选迁移前备份不匹配")
    with zipfile.ZipFile(backup) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    backup_database_fingerprint = manifest.get("database_logical_sha256")
    if (
        manifest.get("format") != "local-rag-pre-migration-backup"
        or manifest.get("format_version") != 1
        or not isinstance(backup_database_fingerprint, str)
        or len(backup_database_fingerprint) != 64
    ):
        raise RuntimeError("迁移前备份格式无效")
    if (
        marker_payload.get("database_logical_sha256")
        != backup_database_fingerprint
    ):
        raise RuntimeError("恢复演练数据库逻辑指纹与备份不匹配")

    candidate = database.with_name(f".{database.name}.migrated-{uuid4().hex}")
    retained = database.with_name(
        f"{database.name}.pre-cutover-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    with InstanceLock(instance_lock_path(settings.DATA_DIR)):
        if sqlite_logical_sha256(database) != backup_database_fingerprint:
            raise RuntimeError(
                "真实数据库在迁移前备份之后发生变化，拒绝最终切换；"
                "请重新生成备份并完成恢复演练"
            )
        report = migrate_copy(database, candidate)
        os.replace(database, retained)
        try:
            os.replace(candidate, database)
        except Exception:
            os.replace(retained, database)
            raise
    return {**report, "retained_original": str(retained), "cutover": True}


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    copy_parser = subparsers.add_parser("copy-upgrade")
    copy_parser.add_argument("--source", type=Path, required=True)
    copy_parser.add_argument("--target", type=Path, required=True)
    cutover = subparsers.add_parser("final-cutover")
    cutover.add_argument("--database", type=Path, required=True)
    cutover.add_argument("--pre-migration-backup", type=Path, required=True)
    cutover.add_argument("--restore-drill", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "copy-upgrade":
        report = migrate_copy(args.source, args.target)
    else:
        report = final_cutover(
            args.database, args.pre_migration_backup, args.restore_drill
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Create an offline, migration-independent physical backup.

This script intentionally imports no application models and requires the API
instance lock.  It is the only backup that physically copies the Chroma
directory, which is safe here because acquiring the lock proves the API/worker
process is stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.database.sqlite_fingerprint import sqlite_logical_sha256


FORMAT_VERSION = 1
BUFFER_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def _iter_regular_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise RuntimeError(f"离线备份拒绝符号链接：{path}")
        if path.is_file():
            yield path


def _snapshot_sqlite(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite 数据库不存在：{source}")
    with closing(
        sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    ) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(f"SQLite 快照完整性检查失败：{result}")


def create_backup(
    *,
    database_path: Path,
    chroma_dir: Path,
    upload_dir: Path,
    data_dir: Path,
    output: Path,
) -> Path:
    """Create an atomic ZIP archive after obtaining the live-instance lock."""

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"目标备份已存在，拒绝覆盖：{output}")
    partial = output.with_name(f"{output.name}.partial")
    snapshot = output.with_name(f".{output.name}.sqlite-snapshot")
    if partial.exists() or snapshot.exists():
        raise FileExistsError(
            f"发现同名遗留临时文件，请先人工核对并单独处理：{partial} / {snapshot}"
        )

    entries: list[tuple[Path, str]] = []
    lock = InstanceLock(instance_lock_path(data_dir))
    try:
        with lock:
            _snapshot_sqlite(database_path.resolve(), snapshot)
            entries.append((snapshot, "metadata/local_rag_chat.db"))
            for root, prefix in ((chroma_dir, "chroma"), (upload_dir, "uploads")):
                resolved_root = root.expanduser().resolve()
                for path in _iter_regular_files(resolved_root):
                    relative = path.relative_to(resolved_root).as_posix()
                    entries.append((path, f"{prefix}/{relative}"))

            members = [
                {
                    "name": archive_name,
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path, archive_name in entries
            ]
            manifest = {
                "format": "local-rag-pre-migration-backup",
                "format_version": FORMAT_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "backup_type": "offline-physical",
                "sqlite_consistency": "sqlite-backup-api",
                "cross_store_transaction": False,
                "database_logical_sha256": sqlite_logical_sha256(snapshot),
                "members": members,
            }
            manifest_bytes = json.dumps(
                manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")

            with zipfile.ZipFile(
                partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for path, archive_name in entries:
                    archive.write(path, archive_name)
                archive.writestr("manifest.json", manifest_bytes)
            os.replace(partial, output)
    finally:
        if snapshot.exists():
            snapshot.unlink()
    return output


def _default_output() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "backups" / f"pre-migration-{stamp}.zip"


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="API 停止后创建一次性迁移前物理备份"
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "data" / "metadata" / "local_rag_chat.db",
    )
    parser.add_argument(
        "--chroma-dir", type=Path, default=PROJECT_ROOT / "data" / "chroma"
    )
    parser.add_argument(
        "--upload-dir", type=Path, default=PROJECT_ROOT / "data" / "uploads"
    )
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--output", type=Path, default=_default_output())
    args = parser.parse_args()

    backup_path = create_backup(
        database_path=args.database,
        chroma_dir=args.chroma_dir,
        upload_dir=args.upload_dir,
        data_dir=args.data_dir,
        output=args.output,
    )
    print(backup_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

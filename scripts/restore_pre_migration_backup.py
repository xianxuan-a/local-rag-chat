"""Offline restore drill for the unsigned, locally created physical backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import unicodedata
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.config import get_settings
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.database.sqlite_fingerprint import sqlite_logical_sha256


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def restore_drill(archive_path: Path, target: Path) -> Path:
    settings = get_settings()
    archive_path = archive_path.expanduser().resolve()
    target = target.expanduser().resolve()
    if target.exists():
        raise FileExistsError(target)
    staging = target.with_name(f".{target.name}.staging-{uuid4().hex}")
    with InstanceLock(instance_lock_path(settings.DATA_DIR)):
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise RuntimeError("归档含重复成员")
            windows = [
                unicodedata.normalize("NFKC", name).casefold() for name in names
            ]
            if len(windows) != len(set(windows)):
                raise RuntimeError("归档含 Windows 大小写冲突")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "local-rag-pre-migration-backup":
                raise RuntimeError("迁移前备份 Manifest 无效")
            expected = {item["name"]: item for item in manifest["members"]}
            if set(expected) != set(names) - {"manifest.json"}:
                raise RuntimeError("Manifest 成员集合不一致")
            staging.mkdir(parents=True, exist_ok=False)
            for name, item in expected.items():
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in name
                    or "\x00" in name
                ):
                    raise RuntimeError(f"不安全成员路径：{name}")
                destination = (staging / path).resolve()
                if os.path.commonpath((str(staging), str(destination))) != str(staging):
                    raise RuntimeError("成员逃逸 staging")
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(name) as source, destination.open("xb") as sink:
                    while block := source.read(1024 * 1024):
                        digest.update(block)
                        sink.write(block)
                if (
                    destination.stat().st_size != item["size"]
                    or digest.hexdigest() != item["sha256"]
                ):
                    raise RuntimeError(f"成员哈希失败：{name}")
        database = staging / "metadata" / "local_rag_chat.db"
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("恢复数据库完整性检查失败")
        logical_hash = sqlite_logical_sha256(database)
        if logical_hash != manifest.get("database_logical_sha256"):
            raise RuntimeError("恢复数据库逻辑指纹与 Manifest 不一致")
        marker = {
            "archive": str(archive_path),
            "archive_sha256": sha256_file(archive_path),
            "database_integrity": "ok",
            "database_logical_sha256": logical_hash,
        }
        (staging / "pre_migration_restore_drill.json").write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(staging, target)
    return target


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(restore_drill(args.archive, args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

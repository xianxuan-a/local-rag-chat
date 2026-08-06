"""Safely inspect or upgrade the SQLite database used by the local launcher."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.database.migrations import (
    current_revision,
    head_revision,
    upgrade_database,
)
from app.database.sqlite import create_db_engine


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def inspect_database(database: Path) -> dict[str, object]:
    database = database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"数据库不存在：{database}")
    engine = create_db_engine(sqlite_url(database))
    try:
        current = current_revision(engine)
    finally:
        engine.dispose()
    expected = head_revision()
    return {
        "database": str(database),
        "current": current,
        "head": expected,
        "upgrade_required": current != expected,
    }


def _sqlite_backup(source: Path, target: Path) -> None:
    with closing(
        sqlite3.connect(
            f"file:{source.resolve().as_posix()}?mode=ro",
            uri=True,
        )
    ) as source_connection:
        with closing(sqlite3.connect(target)) as target_connection:
            source_connection.backup(target_connection)


def _verify_database(database: Path, expected_revision: str) -> None:
    with closing(sqlite3.connect(database)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        revision_row = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    revision = revision_row[0] if revision_row else None
    if not integrity or integrity[0] != "ok":
        raise RuntimeError(f"迁移后数据库完整性检查失败：{integrity}")
    if foreign_keys:
        raise RuntimeError(f"迁移后数据库存在外键错误：{foreign_keys}")
    if revision != expected_revision:
        raise RuntimeError(
            f"迁移后版本不正确：current={revision}, head={expected_revision}"
        )


def upgrade_database_copy(
    database: Path,
    backup_directory: Path,
) -> dict[str, object]:
    """Upgrade a verified copy, then atomically replace the stopped local DB."""

    status = inspect_database(database)
    database = Path(str(status["database"]))
    current = status["current"]
    expected = str(status["head"])
    if current is None:
        raise RuntimeError("数据库没有 Alembic 版本，拒绝自动推断或升级")
    if current == expected:
        return {**status, "upgraded": False, "backup": None}

    backup_directory = backup_directory.expanduser().resolve()
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_directory / (
        f"{database.stem}.pre-{current}-to-{expected}-{stamp}.db"
    )
    if backup.exists():
        backup = backup_directory / (
            f"{database.stem}.pre-{current}-to-{expected}-{stamp}-{uuid4().hex[:8]}.db"
        )
    candidate = database.with_name(
        f".{database.name}.upgrade-{uuid4().hex}.db"
    )

    try:
        _sqlite_backup(database, backup)
        shutil.copy2(backup, candidate)
        upgrade_database(sqlite_url(candidate), "head")
        _verify_database(candidate, expected)
        os.replace(candidate, database)
    except Exception:
        if candidate.exists():
            candidate.unlink()
        raise

    return {
        **inspect_database(database),
        "upgraded": True,
        "previous_revision": current,
        "backup": str(backup),
    }


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--database", type=Path, required=True)

    upgrade_parser = subparsers.add_parser("upgrade")
    upgrade_parser.add_argument("--database", type=Path, required=True)
    upgrade_parser.add_argument("--backup-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "status":
        result = inspect_database(args.database)
    else:
        result = upgrade_database_copy(args.database, args.backup_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

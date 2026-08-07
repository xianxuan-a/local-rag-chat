"""Tests for the lock-protected Compose migration entry point."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.core.instance_lock import (
    InstanceLock,
    InstanceLockError,
    instance_lock_path,
)
from app.database.migrations import current_revision, head_revision
from scripts.run_migrations import run_migrations


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_startup_migration_initializes_a_fresh_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database = data_dir / "metadata" / "compose.db"

    revision = run_migrations(_database_url(database), data_dir)

    engine = create_engine(_database_url(database))
    try:
        assert revision == head_revision()
        assert current_revision(engine) == head_revision()
    finally:
        engine.dispose()


def test_startup_migration_fails_while_instance_is_running(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    database = data_dir / "metadata" / "compose.db"

    with InstanceLock(instance_lock_path(data_dir)):
        with pytest.raises(InstanceLockError, match="实例锁"):
            run_migrations(_database_url(database), data_dir)

    assert not database.exists()

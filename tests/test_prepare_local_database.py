"""Safety checks for the local launcher's explicit database updater."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.database.migrations import upgrade_database
from scripts.prepare_local_database import (
    inspect_database,
    sqlite_url,
    upgrade_database_copy,
)


@pytest.mark.parametrize(
    "starting_revision",
    ["0002_auth_jobs_ownership", "0006_dashboard_aggregates"],
)
def test_upgrade_database_copy_keeps_backup_and_reaches_head(
    tmp_path: Path,
    starting_revision: str,
) -> None:
    database = tmp_path / "runtime.db"
    backup_directory = tmp_path / "backups"
    upgrade_database(sqlite_url(database), starting_revision)

    before = inspect_database(database)
    result = upgrade_database_copy(database, backup_directory)
    after = inspect_database(database)

    assert before["current"] == starting_revision
    assert before["upgrade_required"] is True
    assert result["upgraded"] is True
    assert result["previous_revision"] == starting_revision
    assert after["current"] == after["head"]
    assert after["upgrade_required"] is False

    backup = Path(str(result["backup"]))
    assert backup.is_file()
    assert inspect_database(backup)["current"] == starting_revision


def test_upgrade_database_copy_refuses_unversioned_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unversioned.db"
    database.touch()

    with pytest.raises(RuntimeError, match="没有 Alembic 版本"):
        upgrade_database_copy(database, tmp_path / "backups")

    assert list((tmp_path / "backups").glob("*")) == []

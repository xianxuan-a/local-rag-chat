"""Run Alembic while holding the application's single-instance lock."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cli import configure_utf8_stdio
from app.core.instance_lock import InstanceLock, instance_lock_path
from app.database.migrations import head_revision, upgrade_database


def run_migrations(database_url: str, data_dir: Path) -> str:
    """Upgrade one stopped instance and return the resulting head revision."""

    if not database_url.strip():
        raise ValueError("DATABASE_URL is required")
    resolved_data_dir = data_dir.expanduser().resolve()
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    with InstanceLock(instance_lock_path(resolved_data_dir)):
        url = make_url(database_url)
        if (
            url.get_backend_name() == "sqlite"
            and url.database not in (None, "", ":memory:")
        ):
            Path(url.database).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        upgrade_database(database_url)
    return head_revision()


def main() -> int:
    configure_utf8_stdio()
    database_url = os.getenv("DATABASE_URL", "")
    data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
    revision = run_migrations(database_url, data_dir)
    print(f"database migration complete: revision={revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

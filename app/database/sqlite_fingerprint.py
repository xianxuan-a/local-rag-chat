"""Content fingerprinting for stopped SQLite migration cutover proofs."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path


def sqlite_logical_sha256(path: Path) -> str:
    """Hash SQLite's deterministic logical dump, independent of page layout."""

    resolved = path.expanduser().resolve()
    digest = hashlib.sha256()
    with closing(
        sqlite3.connect(
            f"file:{resolved.as_posix()}?mode=ro",
            uri=True,
        )
    ) as connection:
        for statement in connection.iterdump():
            digest.update(statement.encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()

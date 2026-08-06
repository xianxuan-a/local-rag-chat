"""SQLite engine configuration and request-scoped sessions."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.database.migrations import verify_database_at_head


SessionFactory = sessionmaker[Session]


def create_db_engine(database_url: str) -> Engine:
    """Create an engine with the required SQLite durability parameters."""

    url = make_url(database_url)
    engine_options: dict[str, Any] = {"pool_pre_ping": True}
    if url.get_backend_name() == "sqlite":
        _ensure_database_parent(url.database)
        engine_options["connect_args"] = {"check_same_thread": False}
        if url.database in (None, "", ":memory:"):
            engine_options["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_options)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


def _ensure_database_parent(database_path: str | None) -> None:
    if not database_path or database_path == ":memory:":
        return
    Path(database_path).expanduser().resolve().parent.mkdir(
        parents=True, exist_ok=True
    )


def _configure_sqlite_connection(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def create_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def create_tables(engine: Engine) -> None:
    """Compatibility name for revision verification; performs no runtime DDL."""

    verify_database_at_head(engine)


def ensure_runtime_columns(engine: Engine) -> None:
    """Legacy name retained as a non-mutating revision check."""

    verify_database_at_head(engine)


def init_database(database_url: str) -> tuple[Engine, SessionFactory]:
    """Open a migrated database and reject any revision other than head."""

    engine = create_db_engine(database_url)
    try:
        verify_database_at_head(engine)
    except Exception:
        engine.dispose()
        raise
    return engine, create_session_factory(engine)


def get_db(request: Request) -> Generator[Session, None, None]:
    session_factory: SessionFactory | None = getattr(
        request.app.state, "session_factory", None
    )
    if session_factory is None:
        raise RuntimeError("数据库尚未初始化：app.state.session_factory 不存在")
    database_session = session_factory()
    try:
        yield database_session
    finally:
        database_session.close()


init_db = init_database

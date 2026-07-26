"""SQLite engine, table initialization, and request-scoped sessions."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.models import Base


SessionFactory = sessionmaker[Session]


def create_db_engine(database_url: str) -> Engine:
    """Create an engine configured for safe SQLite use in API requests."""

    url = make_url(database_url)
    engine_options: dict[str, Any] = {"pool_pre_ping": True}

    if url.get_backend_name() == "sqlite":
        _ensure_database_parent(url.database)
        engine_options["connect_args"] = {"check_same_thread": False}
        if url.database in (None, "", ":memory:"):
            engine_options["poolclass"] = StaticPool

    engine = create_engine(database_url, **engine_options)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _ensure_database_parent(database_path: str | None) -> None:
    if not database_path or database_path == ":memory:":
        return
    Path(database_path).expanduser().resolve().parent.mkdir(
        parents=True, exist_ok=True
    )


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create the request session factory without opening a connection."""

    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def create_tables(engine: Engine) -> None:
    """Create all currently registered tables idempotently."""

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns(engine)


_RUNTIME_COLUMNS: dict[str, dict[str, str]] = {
    "file_records": {
        "has_active_vectors": "BOOLEAN NOT NULL DEFAULT 0",
        "active_index_config_hash": "VARCHAR(64)",
        "last_successful_indexed_at": "DATETIME",
    },
    "knowledge_bases": {
        "active_collection_name": "VARCHAR(63)",
        "active_embedding_config_hash": "VARCHAR(64)",
        "previous_collection_name": "VARCHAR(63)",
        "previous_embedding_config_hash": "VARCHAR(64)",
        "building_collection_name": "VARCHAR(63)",
        "building_embedding_config_hash": "VARCHAR(64)",
        "cleanup_collection_name": "VARCHAR(63)",
        "rebuild_status": "VARCHAR(8) NOT NULL DEFAULT 'IDLE'",
        "rebuild_run_id": "VARCHAR(36)",
        "building_started_at": "DATETIME",
    },
}


def ensure_runtime_columns(engine: Engine) -> None:
    """Add only the explicitly supported nullable/defaulted runtime columns."""

    inspector = inspect(engine)
    missing: dict[str, list[str]] = {}
    for table_name, columns in _RUNTIME_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        absent = [name for name in columns if name not in existing]
        if absent:
            missing[table_name] = absent

    if not missing:
        return
    if engine.dialect.name != "sqlite":
        details = ", ".join(
            f"{table}: {', '.join(names)}" for table, names in missing.items()
        )
        raise RuntimeError(
            "数据库缺少文件索引运行时字段，请先执行人工迁移：" + details
        )

    with engine.begin() as connection:
        for table_name, column_names in missing.items():
            for column_name in column_names:
                definition = _RUNTIME_COLUMNS[table_name][column_name]
                connection.execute(
                    text(
                        f'ALTER TABLE "{table_name}" '
                        f'ADD COLUMN "{column_name}" {definition}'
                    )
                )


def init_database(database_url: str) -> tuple[Engine, SessionFactory]:
    """Initialize tables and return the engine plus request session factory."""

    engine = create_db_engine(database_url)
    create_tables(engine)
    return engine, create_session_factory(engine)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield one Session from the factory owned by the FastAPI lifespan."""

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

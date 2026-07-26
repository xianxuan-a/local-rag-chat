"""Strict idempotent SQLite compatibility for newly added runtime columns."""

from sqlalchemy import inspect, text

from app.database.sqlite import create_db_engine, ensure_runtime_columns


def test_runtime_columns_are_added_idempotently_to_legacy_tables(tmp_path) -> None:
    engine = create_db_engine(
        f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE knowledge_bases "
                "(id VARCHAR(36) PRIMARY KEY, name VARCHAR(100))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE file_records "
                "(id VARCHAR(36) PRIMARY KEY, knowledge_base_id VARCHAR(36))"
            )
        )

    ensure_runtime_columns(engine)
    ensure_runtime_columns(engine)

    inspector = inspect(engine)
    file_columns = {
        column["name"]
        for column in inspector.get_columns("file_records")
    }
    kb_columns = {
        column["name"]
        for column in inspector.get_columns("knowledge_bases")
    }
    assert {
        "has_active_vectors",
        "active_index_config_hash",
        "last_successful_indexed_at",
    } <= file_columns
    assert {
        "active_collection_name",
        "previous_collection_name",
        "building_collection_name",
        "cleanup_collection_name",
        "rebuild_status",
        "rebuild_run_id",
        "building_started_at",
    } <= kb_columns
    engine.dispose()

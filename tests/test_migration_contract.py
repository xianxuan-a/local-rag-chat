"""Alembic batch-migration, normalized-schema, and downgrade guards."""

from __future__ import annotations

import sqlite3
import json
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.database.migrations import (
    alembic_config,
    current_revision,
    head_revision,
    upgrade_database,
)
from app.database.schema_contract import (
    compare_schema,
    describe_database,
    describe_metadata,
)
from app.models import Base, KnowledgeBase, User, UserRole, new_uuid
from scripts import migrate_database as migration_tool
from scripts import pre_migration_backup as pre_migration_tool
from scripts import restore_pre_migration_backup as restore_drill_tool
from tests.conftest import make_test_settings


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_0002_backfills_owner_then_matches_normalized_model_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "migration.db"
    database_url = _url(database)
    upgrade_database(database_url, "0001_current_schema")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_bases
                (id, name, description, created_at, updated_at, rebuild_status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "11111111-1111-1111-1111-111111111111",
                "legacy-kb",
                "legacy",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                "IDLE",
            ),
        )
        connection.commit()

    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == head_revision()
        with engine.connect() as connection:
            owner_id = connection.scalar(
                text(
                    "SELECT owner_id FROM knowledge_bases "
                    "WHERE name='legacy-kb'"
                )
            )
            assert owner_id == "00000000-0000-0000-0000-000000000001"
            assert connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).fetchall() == []
        assert compare_schema(
            describe_metadata(Base.metadata),
            describe_database(engine),
        ) == []
    finally:
        engine.dispose()


def test_test_database_downgrade_upgrade_round_trip(tmp_path: Path) -> None:
    database_url = _url(tmp_path / "roundtrip.db")
    upgrade_database(database_url)
    command.downgrade(alembic_config(database_url), "-1")
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0006_dashboard_aggregates"
    finally:
        engine.dispose()
    command.downgrade(alembic_config(database_url), "-1")
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0005_indexes_evaluation_round_three"
    finally:
        engine.dispose()
    command.downgrade(alembic_config(database_url), "-1")
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0004_sessions_chat_round_two"
    finally:
        engine.dispose()
    command.downgrade(alembic_config(database_url), "-1")
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0003_product_settings"
    finally:
        engine.dispose()
    command.downgrade(alembic_config(database_url), "-1")
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0002_auth_jobs_ownership"
    finally:
        engine.dispose()
    upgrade_database(database_url)


def test_0007_downgrade_refuses_web_source_history(tmp_path: Path) -> None:
    database_url = _url(tmp_path / "web-history.db")
    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge_bases
                        (id, owner_id, name, description, rebuild_status,
                         web_access_policy, created_at, updated_at)
                    VALUES
                        (:id, :owner_id, 'web-history', NULL, 'IDLE',
                         'inherit', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": "77777777-7777-7777-7777-777777777777",
                    "owner_id": "00000000-0000-0000-0000-000000000001",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO chat_sessions
                        (id, knowledge_base_id, title, created_at, updated_at)
                    VALUES
                        (:id, :kb_id, 'web history',
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": "88888888-8888-8888-8888-888888888888",
                    "kb_id": "77777777-7777-7777-7777-777777777777",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO chat_messages
                        (id, session_id, role, content, "references", status,
                         requested_mode, effective_mode, web_search_status,
                         web_search_triggered, knowledge_source_count,
                         web_source_count, created_at, updated_at)
                    VALUES
                        (:id, :session_id, 'assistant', '公开信息 [W1]',
                         :references, 'complete', 'hybrid', 'hybrid',
                         'success', 1, 0, 1,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": "99999999-9999-9999-9999-999999999999",
                    "session_id": "88888888-8888-8888-8888-888888888888",
                    "references": json.dumps(
                        [
                            {
                                "citation_number": 1,
                                "source_type": "web",
                                "reference": "[W1]",
                                "title": "Official",
                                "url": "https://example.com/official",
                                "domain": "example.com",
                                "content_preview": "public",
                                "score": 0.9,
                                "metadata": {},
                            }
                        ]
                    ),
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="web source history"):
        command.downgrade(alembic_config(database_url), "-1")

    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0007_retrieval_modes"
    finally:
        engine.dispose()


def test_0006_adds_and_reverses_dashboard_aggregate_indexes(
    tmp_path: Path,
) -> None:
    database_url = _url(tmp_path / "dashboard-round-four.db")
    upgrade_database(database_url, "0005_indexes_evaluation_round_three")
    upgrade_database(database_url, "0006_dashboard_aggregates")
    expected = {
        "knowledge_bases": {"ix_knowledge_bases_owner_updated"},
        "file_records": {
            "ix_file_records_kb_updated",
            "ix_file_records_kb_status_updated",
        },
        "chat_sessions": {"ix_chat_sessions_kb_updated"},
        "chat_messages": {"ix_chat_messages_role_status_created"},
        "jobs": {
            "ix_jobs_type_created",
            "ix_jobs_creator_type_created",
        },
    }
    engine = create_engine(database_url)
    try:
        reflected = inspect(engine)
        for table, names in expected.items():
            actual = {
                str(item["name"]) for item in reflected.get_indexes(table)
            }
            assert names <= actual
    finally:
        engine.dispose()

    command.downgrade(
        alembic_config(database_url),
        "0005_indexes_evaluation_round_three",
    )
    engine = create_engine(database_url)
    try:
        reflected = inspect(engine)
        for table, names in expected.items():
            actual = {
                str(item["name"]) for item in reflected.get_indexes(table)
            }
            assert names.isdisjoint(actual)
        assert current_revision(engine) == "0005_indexes_evaluation_round_three"
    finally:
        engine.dispose()
    upgrade_database(database_url)


def test_0005_backfills_evaluation_jobs_and_enforces_dataset_contract(
    tmp_path: Path,
) -> None:
    database = tmp_path / "indexes-evaluation-round-three.db"
    database_url = _url(database)
    upgrade_database(database_url, "0004_sessions_chat_round_two")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO jobs
                (id, job_type, status, payload, progress, attempt, max_attempts,
                 run_after, budget_reserved_calls, budget_used_calls,
                 budget_reserved_tokens, budget_used_tokens,
                 created_at, updated_at)
            VALUES (?, 'RAG_EVALUATION', 'SUCCEEDED', '{}', 100, 1, 1,
                    ?, 0, 0, 0, 0, ?, ?)
            """,
            (
                "50000000-0000-0000-0000-000000000001",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
            ),
        )
        connection.commit()

    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        reflected = inspect(engine)
        assert "evaluation_datasets" in reflected.get_table_names()
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT evaluation_mode, evaluation_run_name FROM jobs "
                    "WHERE id='50000000-0000-0000-0000-000000000001'"
                )
            ).one()
            assert row.evaluation_mode == "rag"
            assert row.evaluation_run_name == "历史评测"
            assert connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).fetchall() == []
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "UPDATE jobs SET evaluation_mode='judge' "
                        "WHERE id='50000000-0000-0000-0000-000000000001'"
                    )
                )
    finally:
        engine.dispose()

    command.downgrade(
        alembic_config(database_url),
        "0004_sessions_chat_round_two",
    )
    engine = create_engine(database_url)
    try:
        reflected = inspect(engine)
        assert "evaluation_datasets" not in reflected.get_table_names()
        assert "evaluation_mode" not in {
            item["name"] for item in reflected.get_columns("jobs")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM jobs")) == 1
    finally:
        engine.dispose()
    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == head_revision()
    finally:
        engine.dispose()


def test_0004_backfills_chat_state_and_enforces_constraints(
    tmp_path: Path,
) -> None:
    database = tmp_path / "chat-round-two.db"
    database_url = _url(database)
    upgrade_database(database_url, "0003_product_settings")
    user_id = "10000000-0000-0000-0000-000000000001"
    assistant_id = "30000000-0000-0000-0000-000000000002"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO users
                (id, username, username_normalized, email, email_normalized,
                 password_hash, role, is_active, must_change_password,
                 created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, ?, ?, 1, 0, ?, ?)
            """,
            (
                user_id,
                "migration-owner",
                "migration-owner",
                "!",
                "ADMIN",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO knowledge_bases
                (id, name, description, created_at, updated_at,
                 rebuild_status, owner_id)
            VALUES (?, ?, NULL, ?, ?, 'IDLE', ?)
            """,
            (
                "20000000-0000-0000-0000-000000000001",
                "migration-chat-kb",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                user_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO chat_sessions
                (id, knowledge_base_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "30000000-0000-0000-0000-000000000000",
                "20000000-0000-0000-0000-000000000001",
                "legacy",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
            ),
        )
        connection.executemany(
            """
            INSERT INTO chat_messages
                (id, session_id, role, content, "references", created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "30000000-0000-0000-0000-000000000001",
                    "30000000-0000-0000-0000-000000000000",
                    "user",
                    "legacy question",
                    "[]",
                    "2026-01-01 00:00:01",
                ),
                (
                    assistant_id,
                    "30000000-0000-0000-0000-000000000000",
                    "assistant",
                    "legacy answer",
                    (
                        '[{"file_id":"20000000-0000-0000-0000-000000000001",'
                        '"file_name":"legacy.txt","chunk_id":"chunk-1",'
                        '"content_preview":"legacy","score":0.9}]'
                    ),
                    "2026-01-01 00:00:02",
                ),
            ),
        )
        connection.commit()

    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    'SELECT status, updated_at, reply_to_message_id, "references" '
                    "FROM chat_messages WHERE id=:message_id"
                ),
                {"message_id": assistant_id},
            ).one()
            assert row.status == "complete"
            assert row.updated_at is not None
            assert (
                row.reply_to_message_id
                == "30000000-0000-0000-0000-000000000001"
            )
            references = json.loads(row.references)
            assert references[0]["citation_number"] == 1
            assert references[0]["metadata"] == {}
        reflected = inspect(engine)
        assert "message_feedbacks" in reflected.get_table_names()
        assert {
            constraint["name"]
            for constraint in reflected.get_check_constraints("chat_messages")
        } == {"ck_chat_messages_status"}
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "UPDATE chat_messages SET status='invalid' "
                        "WHERE id=:message_id"
                    ),
                    {"message_id": assistant_id},
                )
    finally:
        engine.dispose()

    command.downgrade(
        alembic_config(database_url),
        "0003_product_settings",
    )
    engine = create_engine(database_url)
    try:
        reflected = inspect(engine)
        assert "message_feedbacks" not in reflected.get_table_names()
        assert "status" not in {
            column["name"]
            for column in reflected.get_columns("chat_messages")
        }
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT COUNT(*) FROM chat_messages")
            ) == 2
    finally:
        engine.dispose()
    upgrade_database(database_url)


def test_downgrade_refuses_cross_owner_duplicate_names(
    tmp_path: Path,
) -> None:
    database_url = _url(tmp_path / "irreversible.db")
    upgrade_database(database_url)
    engine = create_engine(database_url)
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        second_owner = User(
            id=new_uuid(),
            username="owner-two",
            username_normalized="owner-two",
            email="owner-two@example.com",
            email_normalized="owner-two@example.com",
            password_hash="!",
            role=UserRole.USER.value,
            is_active=False,
            must_change_password=True,
        )
        db.add(second_owner)
        db.flush()
        db.add_all(
            (
                KnowledgeBase(
                    owner_id="00000000-0000-0000-0000-000000000001",
                    name="same-name",
                ),
                KnowledgeBase(
                    owner_id=second_owner.id,
                    name="same-name",
                ),
            )
        )
        db.commit()
    engine.dispose()

    with pytest.raises(RuntimeError, match="拒绝 downgrade"):
        command.downgrade(
            alembic_config(database_url), "0001_current_schema"
        )

    engine = create_engine(database_url)
    try:
        assert current_revision(engine) == "0002_auth_jobs_ownership"
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT COUNT(*) FROM knowledge_bases "
                    "WHERE name='same-name'"
                )
            ) == 2
    finally:
        engine.dispose()
    upgrade_database(database_url)


def test_offline_backup_restore_drill_and_guarded_final_cutover(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_test_settings(tmp_path)
    settings.ensure_directories()
    database = settings.METADATA_DIR / "local_rag_chat.db"
    upgrade_database(_url(database), "0001_current_schema")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_bases
                (id, name, description, created_at, updated_at, rebuild_status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "22222222-2222-2222-2222-222222222222",
                "cutover-proof",
                "legacy",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                "IDLE",
            ),
        )
        connection.commit()
    archive = settings.BACKUP_DIR / "pre-migration.zip"
    pre_migration_tool.create_backup(
        database_path=database,
        chroma_dir=settings.CHROMA_DIR,
        upload_dir=settings.UPLOAD_DIR,
        data_dir=settings.DATA_DIR,
        output=archive,
    )
    monkeypatch.setattr(
        restore_drill_tool, "get_settings", lambda: settings
    )
    drill = restore_drill_tool.restore_drill(
        archive, tmp_path / "restore-drill"
    )
    monkeypatch.setattr(migration_tool, "get_settings", lambda: settings)

    report = migration_tool.final_cutover(database, archive, drill)

    engine = create_engine(_url(database))
    try:
        assert current_revision(engine) == head_revision()
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT COUNT(*) FROM knowledge_bases "
                    "WHERE name='cutover-proof'"
                )
            ) == 1
    finally:
        engine.dispose()
    assert report["cutover"] is True
    assert Path(str(report["retained_original"])).is_file()


def test_final_cutover_rejects_database_changed_after_backup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_test_settings(tmp_path)
    settings.ensure_directories()
    database = settings.METADATA_DIR / "local_rag_chat.db"
    upgrade_database(_url(database), "0001_current_schema")
    archive = settings.BACKUP_DIR / "pre-migration.zip"
    pre_migration_tool.create_backup(
        database_path=database,
        chroma_dir=settings.CHROMA_DIR,
        upload_dir=settings.UPLOAD_DIR,
        data_dir=settings.DATA_DIR,
        output=archive,
    )
    monkeypatch.setattr(
        restore_drill_tool, "get_settings", lambda: settings
    )
    drill = restore_drill_tool.restore_drill(
        archive, tmp_path / "restore-drill"
    )
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_bases
                (id, name, description, created_at, updated_at, rebuild_status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "33333333-3333-3333-3333-333333333333",
                "changed-after-backup",
                None,
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                "IDLE",
            ),
        )
        connection.commit()
    monkeypatch.setattr(migration_tool, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="发生变化"):
        migration_tool.final_cutover(database, archive, drill)

    engine = create_engine(_url(database))
    try:
        assert current_revision(engine) == "0001_current_schema"
    finally:
        engine.dispose()

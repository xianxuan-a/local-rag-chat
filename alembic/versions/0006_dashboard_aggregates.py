"""Add bounded Dashboard aggregation indexes."""

from __future__ import annotations

from alembic import op


revision = "0006_dashboard_aggregates"
down_revision = "0005_indexes_evaluation_round_three"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_knowledge_bases_owner_updated",
        "knowledge_bases",
        ["owner_id", "updated_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_file_records_kb_updated",
        "file_records",
        ["knowledge_base_id", "updated_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_file_records_kb_status_updated",
        "file_records",
        ["knowledge_base_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_sessions_kb_updated",
        "chat_sessions",
        ["knowledge_base_id", "updated_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_role_status_created",
        "chat_messages",
        ["role", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_type_created",
        "jobs",
        ["job_type", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_creator_type_created",
        "jobs",
        ["created_by_id", "job_type", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_creator_type_created", table_name="jobs")
    op.drop_index("ix_jobs_type_created", table_name="jobs")
    op.drop_index(
        "ix_chat_messages_role_status_created",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_sessions_kb_updated",
        table_name="chat_sessions",
    )
    op.drop_index(
        "ix_file_records_kb_status_updated",
        table_name="file_records",
    )
    op.drop_index("ix_file_records_kb_updated", table_name="file_records")
    op.drop_index(
        "ix_knowledge_bases_owner_updated",
        table_name="knowledge_bases",
    )

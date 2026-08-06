"""Baseline the exact pre-engineering four-table schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("active_collection_name", sa.String(63), nullable=True),
        sa.Column("active_embedding_config_hash", sa.String(64), nullable=True),
        sa.Column("previous_collection_name", sa.String(63), nullable=True),
        sa.Column("previous_embedding_config_hash", sa.String(64), nullable=True),
        sa.Column("building_collection_name", sa.String(63), nullable=True),
        sa.Column("building_embedding_config_hash", sa.String(64), nullable=True),
        sa.Column("cleanup_collection_name", sa.String(63), nullable=True),
        sa.Column(
            "rebuild_status",
            sa.String(8),
            server_default=sa.text("'IDLE'"),
            nullable=False,
        ),
        sa.Column("rebuild_run_id", sa.String(36), nullable=True),
        sa.Column("building_started_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_bases_name", "knowledge_bases", ["name"], unique=True
    )
    op.create_table(
        "file_records",
        sa.Column("knowledge_base_id", sa.String(36), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("md5", sa.String(32), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "has_active_vectors",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("active_index_config_hash", sa.String(64), nullable=True),
        sa.Column("last_successful_indexed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "chunk_count >= 0", name="ck_file_records_chunk_count"
        ),
        sa.CheckConstraint("file_size > 0", name="ck_file_records_file_size"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_name"),
    )
    op.create_index(
        "ix_file_records_knowledge_base_id",
        "file_records",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index("ix_file_records_md5", "file_records", ["md5"], unique=False)
    op.create_table(
        "chat_sessions",
        sa.Column("knowledge_base_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_knowledge_base_id",
        "chat_sessions",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_table(
        "chat_messages",
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(9), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_session_id",
        "chat_messages",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_knowledge_base_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index("ix_file_records_md5", table_name="file_records")
    op.drop_index("ix_file_records_knowledge_base_id", table_name="file_records")
    op.drop_table("file_records")
    op.drop_index("ix_knowledge_bases_name", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

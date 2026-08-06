"""Persist chat lifecycle, reply identity, and assistant feedback."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "0004_sessions_chat_round_two"
down_revision = "0003_product_settings"
branch_labels = None
depends_on = None

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table(
        "chat_messages",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(16),
                server_default="complete",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("error_code", sa.String(64), nullable=True))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("reply_to_message_id", sa.String(36), nullable=True)
        )
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE chat_messages SET updated_at = created_at")
    )

    rows = connection.execute(
        sa.text(
            "SELECT id, session_id, role FROM chat_messages "
            "ORDER BY session_id, created_at, id"
        )
    ).fetchall()
    latest_user: dict[str, str] = {}
    paired_users: set[str] = set()
    reply_pairs: list[tuple[str, str]] = []
    for message_id, session_id, role in rows:
        if role == "user":
            latest_user[str(session_id)] = str(message_id)
            continue
        if role != "assistant":
            continue
        user_id = latest_user.get(str(session_id))
        if user_id is None or user_id in paired_users:
            continue
        reply_pairs.append((str(message_id), user_id))
        paired_users.add(user_id)

    reference_rows = connection.execute(
        sa.text(
            'SELECT id, "references" FROM chat_messages '
            "WHERE role = 'assistant'"
        )
    ).fetchall()
    for message_id, raw_references in reference_rows:
        try:
            references = (
                json.loads(raw_references)
                if isinstance(raw_references, str)
                else raw_references
            )
        except (TypeError, ValueError):
            continue
        if not isinstance(references, list):
            continue
        changed = False
        for index, reference in enumerate(references, start=1):
            if not isinstance(reference, dict):
                continue
            if "citation_number" not in reference:
                reference["citation_number"] = index
                changed = True
            if "metadata" not in reference:
                reference["metadata"] = {}
                changed = True
        if changed:
            connection.execute(
                sa.text(
                    'UPDATE chat_messages SET "references" = :references '
                    "WHERE id = :message_id"
                ),
                {
                    "references": json.dumps(
                        references,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "message_id": str(message_id),
                },
            )

    with op.batch_alter_table(
        "chat_messages",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )
        batch.create_check_constraint(
            "ck_chat_messages_status",
            "status IN ('complete', 'streaming', 'failed', 'cancelled')",
        )
        batch.create_foreign_key(
            "fk_chat_messages_reply_to_message_id_chat_messages",
            "chat_messages",
            ["reply_to_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_chat_messages_reply_to_message_id",
            ["reply_to_message_id"],
        )

    # Apply self-references only after SQLite's final batch table recreation.
    # Otherwise dropping the source table can trigger SET NULL on the copied
    # rows because the temporary table's self-FK still targets that source.
    for message_id, user_id in reply_pairs:
        connection.execute(
            sa.text(
                "UPDATE chat_messages SET reply_to_message_id = :user_id "
                "WHERE id = :message_id"
            ),
            {"user_id": user_id, "message_id": message_id},
        )

    op.create_index(
        "ix_chat_messages_reply_to_message_id",
        "chat_messages",
        ["reply_to_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_session_status",
        "chat_messages",
        ["session_id", "status"],
        unique=False,
    )

    op.create_table(
        "message_feedbacks",
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("value", sa.String(16), nullable=False),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "value IN ('like', 'dislike')",
            name="ck_message_feedbacks_value",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name="fk_message_feedbacks_message_id_chat_messages",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_message_feedbacks_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_feedbacks"),
        sa.UniqueConstraint(
            "message_id",
            name="uq_message_feedbacks_message_id",
        ),
    )
    op.create_index(
        "ix_message_feedbacks_message_id",
        "message_feedbacks",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_message_feedbacks_message_id",
        table_name="message_feedbacks",
    )
    op.drop_table("message_feedbacks")

    op.drop_index(
        "ix_chat_messages_session_status",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_session_created",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_reply_to_message_id",
        table_name="chat_messages",
    )
    with op.batch_alter_table(
        "chat_messages",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(
            "uq_chat_messages_reply_to_message_id",
            type_="unique",
        )
        batch.drop_constraint(
            "fk_chat_messages_reply_to_message_id_chat_messages",
            type_="foreignkey",
        )
        # The batch naming convention re-applies the ``ck`` template to the
        # reflected explicit name while recreating SQLite tables.
        batch.drop_constraint(
            "ck_chat_messages_ck_chat_messages_status",
            type_="check",
        )
        batch.drop_column("updated_at")
        batch.drop_column("reply_to_message_id")
        batch.drop_column("error_message")
        batch.drop_column("error_code")
        batch.drop_column("status")

"""Create one globally unique namespace for usernames and email addresses."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from alembic import op
import sqlalchemy as sa


revision = "0008_user_identities"
down_revision = "0007_retrieval_modes"
branch_labels = None
depends_on = None


def _identity_conflicts(connection: sa.Connection) -> list[tuple[str, int]]:
    rows = connection.exec_driver_sql(
        """
        WITH identity_values AS (
            SELECT id AS user_id, username_normalized AS normalized_value
            FROM users
            WHERE username_normalized IS NOT NULL
              AND username_normalized != ''
            UNION ALL
            SELECT id AS user_id, email_normalized AS normalized_value
            FROM users
            WHERE email_normalized IS NOT NULL
              AND email_normalized != ''
        )
        SELECT normalized_value, COUNT(DISTINCT user_id) AS user_count
        FROM identity_values
        GROUP BY normalized_value
        HAVING COUNT(DISTINCT user_id) > 1
        ORDER BY normalized_value
        """
    ).fetchall()
    return [(str(value), int(count)) for value, count in rows]


def upgrade() -> None:
    connection = op.get_bind()
    conflicts = _identity_conflicts(connection)
    if conflicts:
        summaries = [
            (
                hashlib.sha256(value.encode("utf-8")).hexdigest()[:12],
                count,
            )
            for value, count in conflicts
        ]
        raise RuntimeError(
            "拒绝迁移：检测到跨账户登录标识冲突；"
            f"请先人工处理。conflicts={summaries}"
        )

    op.create_table(
        "user_identities",
        sa.Column("normalized_value", sa.String(640), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_identities_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "normalized_value", name="pk_user_identities"
        ),
    )
    op.create_index(
        "ix_user_identities_user_id",
        "user_identities",
        ["user_id"],
        unique=False,
    )

    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        sa.text(
            """
            INSERT INTO user_identities(normalized_value, user_id, created_at)
            SELECT username_normalized, id, :created_at
            FROM users
            WHERE username_normalized IS NOT NULL
              AND username_normalized != ''
            """
        ).bindparams(created_at=now)
    )
    connection.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO user_identities(
                normalized_value, user_id, created_at
            )
            SELECT email_normalized, id, :created_at
            FROM users
            WHERE email_normalized IS NOT NULL
              AND email_normalized != ''
            """
        ).bindparams(created_at=now)
    )

    violations = connection.exec_driver_sql(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if violations:
        raise RuntimeError(f"0008 外键检查失败：{violations}")


def downgrade() -> None:
    op.drop_index(
        "ix_user_identities_user_id", table_name="user_identities"
    )
    op.drop_table("user_identities")

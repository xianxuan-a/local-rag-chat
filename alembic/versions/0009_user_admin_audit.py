"""Add persistent administrator audit events and last-admin protection."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_user_admin_audit"
down_revision = "0008_user_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_admin_audit_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("target_user_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action IN ('USER_UPDATED')",
            name="ck_user_admin_audit_events_action",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_user_admin_audit_events_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_user_admin_audit_events_target_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_admin_audit_events"),
    )
    op.create_index(
        "ix_user_admin_audit_events_target_created",
        "user_admin_audit_events",
        ["target_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_user_admin_audit_events_actor_created",
        "user_admin_audit_events",
        ["actor_user_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE TRIGGER trg_users_preserve_last_active_admin
        BEFORE UPDATE OF role, is_active ON users
        WHEN OLD.role = 'ADMIN'
          AND OLD.is_active = 1
          AND (NEW.role != 'ADMIN' OR NEW.is_active = 0)
          AND NOT EXISTS (
              SELECT 1 FROM users
              WHERE id != OLD.id AND role = 'ADMIN' AND is_active = 1
          )
        BEGIN
            SELECT RAISE(ABORT, 'last_active_admin');
        END
        """
    )

    connection = op.get_bind()
    violations = connection.exec_driver_sql(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if violations:
        raise RuntimeError(f"0009 外键检查失败：{violations}")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_users_preserve_last_active_admin")
    op.drop_index(
        "ix_user_admin_audit_events_actor_created",
        table_name="user_admin_audit_events",
    )
    op.drop_index(
        "ix_user_admin_audit_events_target_created",
        table_name="user_admin_audit_events",
    )
    op.drop_table("user_admin_audit_events")

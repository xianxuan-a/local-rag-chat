"""Add authentication, ownership, durable jobs, and recovery bindings."""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0002_auth_jobs_ownership"
down_revision = "0001_current_schema"
branch_labels = None
depends_on = None

BOOTSTRAP_USER_ID = "00000000-0000-0000-0000-000000000001"
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    now = datetime.now(timezone.utc).isoformat()
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("username_normalized", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("email_normalized", sa.String(640), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), server_default="USER", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('ADMIN', 'USER')", name="user_role"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username_normalized", name="uq_users_username_normalized"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
    )
    op.bulk_insert(
        sa.table(
            "users",
            sa.column("id", sa.String()),
            sa.column("username", sa.String()),
            sa.column("username_normalized", sa.String()),
            sa.column("email", sa.String()),
            sa.column("email_normalized", sa.String()),
            sa.column("password_hash", sa.String()),
            sa.column("role", sa.String()),
            sa.column("is_active", sa.Boolean()),
            sa.column("must_change_password", sa.Boolean()),
            sa.column("created_at", sa.String()),
            sa.column("updated_at", sa.String()),
        ),
        [
            {
                "id": BOOTSTRAP_USER_ID,
                "username": "bootstrap-admin",
                "username_normalized": "bootstrap-admin",
                "email": None,
                "email_normalized": None,
                "password_hash": "!",
                "role": "ADMIN",
                "is_active": False,
                "must_change_password": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    # The nullable-add/backfill sequence is deliberate and precedes recreation.
    op.add_column(
        "knowledge_bases",
        sa.Column("owner_id", sa.String(36), nullable=True),
    )
    op.execute(
        sa.text("UPDATE knowledge_bases SET owner_id = :owner_id").bindparams(
            owner_id=BOOTSTRAP_USER_ID
        )
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), server_default="QUEUED", nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("resource_name_snapshot", sa.String(255), nullable=True),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stage", sa.String(100), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("run_after", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("retry_of_job_id", sa.String(36), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("collection_name", sa.String(63), nullable=True),
        sa.Column("embedding_config_hash", sa.String(64), nullable=True),
        sa.Column("dataset_sha256", sa.String(64), nullable=True),
        sa.Column("evaluation_config_hash", sa.String(64), nullable=True),
        sa.Column("budget_total_calls", sa.Integer(), nullable=True),
        sa.Column("budget_reserved_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("budget_used_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("budget_total_tokens", sa.Integer(), nullable=True),
        sa.Column("budget_reserved_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("budget_used_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("report_path", sa.Text(), nullable=True),
        sa.Column("report_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED')",
            name="job_status",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="job_progress"),
        sa.CheckConstraint("attempt >= 0 AND max_attempts >= 1", name="job_attempts"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL",
            name="fk_jobs_created_by_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_job_id"], ["jobs.id"], ondelete="SET NULL",
            name="fk_jobs_retry_of_job_id_jobs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", "run_after", "lease_expires_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_resource",
        "jobs",
        ["resource_type", "resource_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_collection_pin",
        "jobs",
        ["job_type", "status", "collection_name"],
        unique=False,
    )

    with op.batch_alter_table(
        "knowledge_bases",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.alter_column(
            "owner_id",
            existing_type=sa.String(36),
            nullable=False,
        )
        batch.add_column(sa.Column("rebuild_job_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_bases_owner_id_users",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_knowledge_bases_rebuild_job_id_jobs",
            "jobs",
            ["rebuild_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_knowledge_bases_owner_id_name", ["owner_id", "name"]
        )
    op.drop_index("ix_knowledge_bases_name", table_name="knowledge_bases")
    op.create_index(
        "ix_knowledge_bases_owner_id",
        "knowledge_bases",
        ["owner_id"],
        unique=False,
    )

    with op.batch_alter_table(
        "file_records",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.add_column(sa.Column("processing_job_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_file_records_processing_job_id_jobs",
            "jobs",
            ["processing_job_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "runtime_state",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("owner_job_id", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_job_id"],
            ["jobs.id"],
            ondelete="SET NULL",
            name="fk_runtime_state_owner_job_id_jobs",
        ),
        sa.PrimaryKeyConstraint("key", name="pk_runtime_state"),
    )

    connection = op.get_bind()
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"0002 外键检查失败：{violations}")


def downgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.exec_driver_sql(
        """
        SELECT name, COUNT(DISTINCT owner_id)
        FROM knowledge_bases
        GROUP BY name
        HAVING COUNT(DISTINCT owner_id) > 1
        """
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "拒绝 downgrade：不同所有者已存在同名知识库，旧版全局唯一约束不可逆。"
        )

    op.drop_table("runtime_state")
    with op.batch_alter_table(
        "file_records",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(
            "fk_file_records_processing_job_id_jobs", type_="foreignkey"
        )
        batch.drop_column("processing_job_id")

    op.drop_index("ix_knowledge_bases_owner_id", table_name="knowledge_bases")
    with op.batch_alter_table(
        "knowledge_bases",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(
            "fk_knowledge_bases_rebuild_job_id_jobs", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_knowledge_bases_owner_id_users", type_="foreignkey"
        )
        batch.drop_constraint("uq_knowledge_bases_owner_id_name", type_="unique")
        batch.drop_column("rebuild_job_id")
        batch.drop_column("owner_id")
    op.create_index(
        "ix_knowledge_bases_name", "knowledge_bases", ["name"], unique=True
    )
    op.drop_index("ix_jobs_collection_pin", table_name="jobs")
    op.drop_index("ix_jobs_resource", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("users")

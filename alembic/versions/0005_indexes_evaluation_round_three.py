"""Add reusable evaluation datasets and typed evaluation Job fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_indexes_evaluation_round_three"
down_revision = "0004_sessions_chat_round_two"
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
    op.create_table(
        "evaluation_datasets",
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_evaluation_datasets_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_datasets"),
        sa.UniqueConstraint(
            "owner_id",
            "name",
            name="uq_evaluation_datasets_owner_id_name",
        ),
    )
    op.create_index(
        "ix_evaluation_datasets_owner_created",
        "evaluation_datasets",
        ["owner_id", "created_at", "id"],
        unique=False,
    )

    with op.batch_alter_table(
        "jobs",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.add_column(
            sa.Column("evaluation_dataset_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column("evaluation_mode", sa.String(16), nullable=True)
        )
        batch.add_column(
            sa.Column("evaluation_run_name", sa.String(200), nullable=True)
        )
        batch.create_foreign_key(
            "fk_jobs_evaluation_dataset_id_evaluation_datasets",
            "evaluation_datasets",
            ["evaluation_dataset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_jobs_evaluation_mode",
            "evaluation_mode IS NULL OR evaluation_mode IN ('retrieval','rag')",
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE jobs SET evaluation_mode = 'rag', "
            "evaluation_run_name = '历史评测' "
            "WHERE job_type = 'RAG_EVALUATION'"
        )
    )
    op.create_index(
        "ix_jobs_evaluation_dataset",
        "jobs",
        ["evaluation_dataset_id", "created_at", "id"],
        unique=False,
    )
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"0005 外键检查失败：{violations}")


def downgrade() -> None:
    op.drop_index("ix_jobs_evaluation_dataset", table_name="jobs")
    with op.batch_alter_table(
        "jobs",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(
            "ck_jobs_ck_jobs_evaluation_mode",
            type_="check",
        )
        batch.drop_constraint(
            "fk_jobs_evaluation_dataset_id_evaluation_datasets",
            type_="foreignkey",
        )
        batch.drop_column("evaluation_run_name")
        batch.drop_column("evaluation_mode")
        batch.drop_column("evaluation_dataset_id")

    op.drop_index(
        "ix_evaluation_datasets_owner_created",
        table_name="evaluation_datasets",
    )
    op.drop_table("evaluation_datasets")

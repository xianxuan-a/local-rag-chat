"""Add the singleton non-secret product settings table."""

from alembic import op
import sqlalchemy as sa


revision = "0003_product_settings"
down_revision = "0002_auth_jobs_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_model", sa.String(100), nullable=True),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False),
        sa.Column("retrieval_score_threshold", sa.Float(), nullable=True),
        sa.Column("rag_context_max_chars", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_product_settings_singleton"),
        sa.CheckConstraint(
            "retrieval_top_k BETWEEN 1 AND 100",
            name="ck_product_settings_retrieval_top_k",
        ),
        sa.CheckConstraint(
            "retrieval_score_threshold IS NULL OR "
            "retrieval_score_threshold BETWEEN -1.0 AND 1.0",
            name="ck_product_settings_score_threshold",
        ),
        sa.CheckConstraint(
            "rag_context_max_chars BETWEEN 1000 AND 1000000",
            name="ck_product_settings_context_chars",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_product_settings_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_settings"),
    )


def downgrade() -> None:
    op.drop_table("product_settings")

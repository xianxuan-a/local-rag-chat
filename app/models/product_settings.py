"""Database-backed, non-secret product settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.core.retrieval_modes import (
    DEFAULT_FRESHNESS_TERMS,
    RetrievalMode,
)

if TYPE_CHECKING:
    from app.models.user import User


class ProductSettings(TimestampMixin, Base):
    """A singleton row containing the supported runtime overrides."""

    __tablename__ = "product_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_product_settings_singleton"),
        CheckConstraint(
            "retrieval_top_k BETWEEN 1 AND 100",
            name="ck_product_settings_retrieval_top_k",
        ),
        CheckConstraint(
            "retrieval_score_threshold IS NULL OR "
            "retrieval_score_threshold BETWEEN -1.0 AND 1.0",
            name="ck_product_settings_score_threshold",
        ),
        CheckConstraint(
            "rag_context_max_chars BETWEEN 1000 AND 1000000",
            name="ck_product_settings_context_chars",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    chat_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retrieval_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_score_threshold: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    rag_context_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    web_search_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    default_retrieval_mode: Mapped[str] = mapped_column(
        String(32),
        default=RetrievalMode.KNOWLEDGE_FIRST.value,
        server_default=RetrievalMode.KNOWLEDGE_FIRST.value,
        nullable=False,
    )
    retrieval_min_evidence_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    retrieval_freshness_terms: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: list(DEFAULT_FRESHNESS_TERMS),
        server_default=(
            '["今天","当前","目前","最近","最新","现价","现任","刚刚",'
            '"今年政策","today","current","currently","recent","recently",'
            '"latest","now","this year"]'
        ),
        nullable=False,
    )
    updated_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_by: Mapped["User | None"] = relationship()

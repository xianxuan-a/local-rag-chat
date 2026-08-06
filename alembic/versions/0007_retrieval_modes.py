"""Add retrieval modes, web policy, and per-answer retrieval audit data."""

from __future__ import annotations

import json
import re

from alembic import op
import sqlalchemy as sa


revision = "0007_retrieval_modes"
down_revision = "0006_dashboard_aggregates"
branch_labels = None
depends_on = None

FRESHNESS_TERMS_JSON = (
    '["今天","当前","目前","最近","最新","现价","现任","刚刚",'
    '"今年政策","today","current","currently","recent","recently",'
    '"latest","now","this year"]'
)
def upgrade() -> None:
    connection = op.get_bind()
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "web_access_policy",
            sa.String(16),
            server_default="inherit",
            nullable=False,
        ),
    )
    op.add_column(
        "product_settings",
        sa.Column(
            "web_search_enabled",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "product_settings",
        sa.Column(
            "default_retrieval_mode",
            sa.String(32),
            server_default="knowledge_first",
            nullable=False,
        ),
    )
    op.add_column(
        "product_settings",
        sa.Column(
            "retrieval_min_evidence_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "product_settings",
        sa.Column(
            "retrieval_freshness_terms",
            sa.JSON(),
            server_default=sa.text(f"'{FRESHNESS_TERMS_JSON}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column("requested_mode", sa.String(32), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("effective_mode", sa.String(32), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "web_search_triggered",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "web_search_status",
            sa.String(32),
            server_default="not_requested",
            nullable=False,
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column("web_trigger_reason", sa.String(64), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "knowledge_source_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "web_source_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column("fallback_reason", sa.String(128), nullable=True),
    )
    _upgrade_historical_references(connection)


def _upgrade_historical_references(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            'SELECT id, content, "references" FROM chat_messages '
            "WHERE role = 'assistant'"
        )
    ).fetchall()
    for message_id, content, raw_references in rows:
        try:
            references = (
                json.loads(raw_references)
                if isinstance(raw_references, str)
                else raw_references
            )
        except (TypeError, ValueError):
            references = []
        if not isinstance(references, list):
            references = []
        normalized: list[dict[str, object]] = []
        citation_numbers: set[int] = set()
        for index, raw_reference in enumerate(references, start=1):
            if not isinstance(raw_reference, dict):
                continue
            reference = dict(raw_reference)
            raw_number = reference.get("citation_number", index)
            try:
                citation_number = max(1, int(raw_number))
            except (TypeError, ValueError):
                citation_number = index
            citation_numbers.add(citation_number)
            reference["citation_number"] = citation_number
            reference["source_type"] = "knowledge_base"
            reference["reference"] = f"[K{citation_number}]"
            reference["title"] = str(
                reference.get("file_name") or "历史知识库来源"
            )
            normalized.append(reference)
        upgraded_content = str(content or "")
        for citation_number in sorted(citation_numbers):
            upgraded_content = re.sub(
                rf"\[S0*{citation_number}\]",
                f"[K{citation_number}]",
                upgraded_content,
            )
        connection.execute(
            sa.text(
                'UPDATE chat_messages SET content = :content, "references" = '
                ":references, requested_mode = 'knowledge_only', "
                "effective_mode = 'knowledge_only', "
                "web_search_triggered = 0, "
                "web_search_status = 'not_requested', "
                "knowledge_source_count = :knowledge_count, "
                "web_source_count = 0 WHERE id = :message_id"
            ),
            {
                "content": upgraded_content,
                "references": json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "knowledge_count": len(normalized),
                "message_id": str(message_id),
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            'SELECT id, content, "references" FROM chat_messages '
            "WHERE role = 'assistant'"
        )
    ).fetchall()
    converted: list[tuple[str, str, str]] = []
    for message_id, content, raw_references in rows:
        try:
            references = (
                json.loads(raw_references)
                if isinstance(raw_references, str)
                else raw_references
            )
        except (TypeError, ValueError):
            references = []
        if not isinstance(references, list):
            references = []
        if any(
            isinstance(reference, dict)
            and reference.get("source_type") == "web"
            for reference in references
        ):
            raise RuntimeError(
                "0007 downgrade refused: web source history cannot be "
                "represented by the previous schema"
            )
        citation_numbers: set[int] = set()
        legacy: list[dict[str, object]] = []
        for index, raw_reference in enumerate(references, start=1):
            if not isinstance(raw_reference, dict):
                continue
            reference = dict(raw_reference)
            try:
                citation_number = max(
                    1, int(reference.get("citation_number", index))
                )
            except (TypeError, ValueError):
                citation_number = index
            citation_numbers.add(citation_number)
            reference.pop("source_type", None)
            reference.pop("reference", None)
            reference.pop("title", None)
            legacy.append(reference)
        legacy_content = str(content or "")
        for citation_number in sorted(citation_numbers):
            legacy_content = re.sub(
                rf"\[K0*{citation_number}\]",
                f"[S{citation_number}]",
                legacy_content,
            )
        converted.append(
            (
                str(message_id),
                legacy_content,
                json.dumps(
                    legacy,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )

    for message_id, content, references in converted:
        connection.execute(
            sa.text(
                'UPDATE chat_messages SET content = :content, "references" = '
                ":references WHERE id = :message_id"
            ),
            {
                "content": content,
                "references": references,
                "message_id": message_id,
            },
        )

    op.drop_column("chat_messages", "fallback_reason")
    op.drop_column("chat_messages", "web_source_count")
    op.drop_column("chat_messages", "knowledge_source_count")
    op.drop_column("chat_messages", "web_trigger_reason")
    op.drop_column("chat_messages", "web_search_status")
    op.drop_column("chat_messages", "web_search_triggered")
    op.drop_column("chat_messages", "effective_mode")
    op.drop_column("chat_messages", "requested_mode")
    op.drop_column("product_settings", "retrieval_freshness_terms")
    op.drop_column("product_settings", "retrieval_min_evidence_count")
    op.drop_column("product_settings", "default_retrieval_mode")
    op.drop_column("product_settings", "web_search_enabled")
    op.drop_column("knowledge_bases", "web_access_policy")

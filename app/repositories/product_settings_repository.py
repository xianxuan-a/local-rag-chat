"""Persistence operations for the singleton product-settings row."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ProductSettings


class ProductSettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> ProductSettings | None:
        return self.db.get(ProductSettings, 1)

    def save(
        self,
        *,
        chat_model: str | None,
        retrieval_top_k: int,
        retrieval_score_threshold: float | None,
        rag_context_max_chars: int,
        web_search_enabled: bool,
        default_retrieval_mode: str,
        retrieval_min_evidence_count: int,
        retrieval_freshness_terms: list[str],
        updated_by_id: str,
    ) -> ProductSettings:
        record = self.get()
        if record is None:
            record = ProductSettings(
                id=1,
                chat_model=chat_model,
                retrieval_top_k=retrieval_top_k,
                retrieval_score_threshold=retrieval_score_threshold,
                rag_context_max_chars=rag_context_max_chars,
                web_search_enabled=web_search_enabled,
                default_retrieval_mode=default_retrieval_mode,
                retrieval_min_evidence_count=retrieval_min_evidence_count,
                retrieval_freshness_terms=list(
                    retrieval_freshness_terms
                ),
                updated_by_id=updated_by_id,
            )
            self.db.add(record)
        else:
            record.chat_model = chat_model
            record.retrieval_top_k = retrieval_top_k
            record.retrieval_score_threshold = retrieval_score_threshold
            record.rag_context_max_chars = rag_context_max_chars
            record.web_search_enabled = web_search_enabled
            record.default_retrieval_mode = default_retrieval_mode
            record.retrieval_min_evidence_count = (
                retrieval_min_evidence_count
            )
            record.retrieval_freshness_terms = list(
                retrieval_freshness_terms
            )
            record.updated_by_id = updated_by_id
        self.db.flush()
        return record

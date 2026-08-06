"""Public schemas for the supported database-backed product settings."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.retrieval_modes import DEFAULT_FRESHNESS_TERMS, RetrievalMode


class ProductSettingsUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    chat_model: str | None = Field(default=None, max_length=100)
    retrieval_top_k: int = Field(ge=1, le=100)
    retrieval_score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    rag_context_max_chars: int = Field(ge=1000, le=1_000_000)
    web_search_enabled: bool = False
    default_retrieval_mode: RetrievalMode = RetrievalMode.KNOWLEDGE_FIRST
    retrieval_min_evidence_count: int = Field(default=1, ge=1, le=100)
    retrieval_freshness_terms: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FRESHNESS_TERMS),
        min_length=1,
        max_length=64,
    )

    @field_validator("chat_model")
    @classmethod
    def normalize_chat_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("retrieval_freshness_terms")
    @classmethod
    def normalize_freshness_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_value in values:
            value = raw_value.strip()
            folded = value.casefold()
            if not value or len(value) > 64:
                raise ValueError("时效词必须为 1 到 64 个字符")
            if folded not in seen:
                seen.add(folded)
                normalized.append(value)
        if not normalized:
            raise ValueError("至少需要一个时效词")
        return normalized


class ProductSettingsResponse(BaseModel):
    chat_model: str | None
    retrieval_top_k: int
    retrieval_score_threshold: float | None
    rag_context_max_chars: int
    web_search_enabled: bool
    default_retrieval_mode: RetrievalMode
    retrieval_min_evidence_count: int
    retrieval_freshness_terms: list[str]
    web_search_provider: str
    web_search_provider_configured: bool
    web_search_allowed_for_current_user: bool
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    vector_metric: str
    dashscope_api_key_configured: bool
    source: str
    updated_at: datetime | None

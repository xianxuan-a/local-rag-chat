"""Request and response contracts for direct retrieval inspection."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    knowledge_base_id: UUID
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)


class RetrievalResult(BaseModel):
    rank: int = Field(ge=1)
    score: float = Field(ge=-1.0, le=1.0)
    file_id: UUID
    file_name: str
    chunk_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResponse(BaseModel):
    result_count: int = Field(ge=0)
    query_time_ms: int = Field(ge=0)
    results: list[RetrievalResult]

"""Evaluation dataset, run, summary, and report-case contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.job import JobResponse


EvaluationMode = Literal["retrieval", "rag"]


class EvaluationDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    original_filename: str
    sha256: str
    size_bytes: int
    case_count: int
    created_at: datetime
    updated_at: datetime


class EvaluationDatasetPage(BaseModel):
    items: list[EvaluationDatasetResponse]
    total: int
    limit: int
    offset: int


class EvaluationRunCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    dataset_id: UUID
    knowledge_base_id: UUID
    run_name: str = Field(min_length=1, max_length=200)
    mode: EvaluationMode = "retrieval"
    top_k: int = Field(default=4, ge=1, le=100)
    score_threshold: float | None = Field(
        default=None, ge=-1.0, le=1.0
    )
    max_calls: int = Field(default=200, ge=1, le=1000)
    max_generation_tokens: int = Field(
        default=100000, ge=0, le=2_000_000
    )
    max_runtime_seconds: int = Field(default=1800, ge=1, le=21600)

    @field_validator("run_name")
    @classmethod
    def normalize_run_name(cls, value: str) -> str:
        return value.strip()


class EvaluationRunResponse(BaseModel):
    job: JobResponse
    dataset: EvaluationDatasetResponse | None
    mode: EvaluationMode
    run_name: str
    outcome: Literal["SUCCESS", "PARTIAL_SUCCESS"] | None = None
    metrics: dict[str, Any] | None = None


class EvaluationRunPage(BaseModel):
    items: list[EvaluationRunResponse]
    total: int
    limit: int
    offset: int


class EvaluationSummaryResponse(BaseModel):
    run_count: int
    dataset_count: int
    status_counts: dict[str, int]


class EvaluationCasePage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    failed_only: bool

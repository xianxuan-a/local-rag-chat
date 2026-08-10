"""Durable Job API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: str
    resource_type: str | None
    resource_id: UUID | None
    resource_name_snapshot: str | None
    progress: int
    stage: str | None
    attempt: int
    max_attempts: int
    run_after: datetime
    lease_expires_at: datetime | None
    retry_of_job_id: UUID | None
    collection_name: str | None
    embedding_config_hash: str | None
    dataset_sha256: str | None
    evaluation_config_hash: str | None
    evaluation_dataset_id: UUID | None
    evaluation_mode: str | None
    evaluation_run_name: str | None
    budget_total_calls: int | None
    budget_reserved_calls: int
    budget_used_calls: int
    budget_total_tokens: int | None
    budget_reserved_tokens: int
    budget_used_tokens: int
    deadline_at: datetime | None
    report_path: str | None
    report_sha256: str | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobPage(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int

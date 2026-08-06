"""Public schemas for the authenticated Dashboard aggregate."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardMetrics(BaseModel):
    knowledge_bases: int = Field(ge=0)
    files_total: int = Field(ge=0)
    files_success: int = Field(ge=0)
    files_in_progress: int = Field(ge=0)
    files_failed: int = Field(ge=0)
    chunks: int = Field(ge=0)
    sessions: int = Field(ge=0)
    user_questions: int = Field(ge=0)
    assistant_answers: int = Field(ge=0)
    active_indexes: int = Field(ge=0)
    building_indexes: int = Field(ge=0)


class DashboardTrendPoint(BaseModel):
    date: date
    uploads: int = Field(ge=0)
    questions: int = Field(ge=0)
    failed_files: int = Field(ge=0)
    index_operations: int = Field(ge=0)
    evaluation_runs: int = Field(ge=0)


class DashboardFileStatusCount(BaseModel):
    status: Literal["PENDING", "PROCESSING", "SUCCESS", "FAILED"]
    count: int = Field(ge=0)


class DashboardRecentFile(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    knowledge_base_name: str
    file_name: str
    file_type: str
    status: Literal["PENDING", "PROCESSING", "SUCCESS", "FAILED"]
    chunk_count: int = Field(ge=0)
    updated_at: datetime


class DashboardRecentSession(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    knowledge_base_name: str
    title: str
    preview: str
    message_count: int = Field(ge=0)
    updated_at: datetime


class DashboardRecentJob(BaseModel):
    id: UUID
    knowledge_base_id: UUID | None
    knowledge_base_name: str
    job_type: str
    status: str
    stage: str | None
    progress: int = Field(ge=0, le=100)
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class DashboardRuntimeStatus(BaseModel):
    chat_configured: bool
    missing_chat_configuration: list[str]
    embedding_key_configured: bool


class DashboardResponse(BaseModel):
    generated_at: datetime
    time_zone: Literal["UTC"] = "UTC"
    window_days: int = Field(ge=1, le=30)
    knowledge_base_id: UUID | None
    metrics: DashboardMetrics
    trend: list[DashboardTrendPoint]
    file_statuses: list[DashboardFileStatusCount]
    recent_files: list[DashboardRecentFile]
    recent_sessions: list[DashboardRecentSession]
    recent_index_jobs: list[DashboardRecentJob]
    recent_evaluations: list[DashboardRecentJob]
    runtime: DashboardRuntimeStatus
    section_errors: dict[str, str] = Field(default_factory=dict)

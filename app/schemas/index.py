"""Public index lifecycle state derived from database pointers and Chroma."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.job import JobResponse


class IndexCollectionResponse(BaseModel):
    collection_name: str
    role: Literal["active", "previous", "building", "cleanup", "orphan"]
    exists: bool
    lifecycle_status: str | None = None
    generation: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    distance_metric: str | None = None
    embedding_config_hash: str | None = None
    file_count: int | None = None
    chunk_count: int | None = None
    safe_to_cleanup: bool = False
    cleanup_reason: str | None = None
    error: str | None = None


class IndexStateResponse(BaseModel):
    knowledge_base_id: UUID
    knowledge_base_name: str
    rebuild_status: str
    rebuild_run_id: str | None
    building_started_at: datetime | None
    collections: list[IndexCollectionResponse]
    latest_job: JobResponse | None


class CleanupIndexesRequest(BaseModel):
    cleanup_previous: bool = False
    cleanup_orphans: bool = False

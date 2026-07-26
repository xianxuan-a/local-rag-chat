"""Knowledge-base collection rebuild and maintenance responses."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class RebuildFailure(BaseModel):
    file_id: UUID
    file_name: str
    error: str


class RebuildResponse(BaseModel):
    status: Literal["SUCCESS", "PARTIAL_SUCCESS", "FAILED"]
    knowledge_base_id: UUID
    total: int
    succeeded: int
    failed: int
    failures: list[RebuildFailure]
    source_collection: str | None
    target_collection: str
    embedding_config_hash: str
    generation: str
    switched: bool
    cleanup_pending: bool = False


class CollectionMaintenanceResponse(BaseModel):
    status: Literal["SUCCESS", "NOOP"]
    knowledge_base_id: UUID
    collection_name: str | None = None
    already_missing: bool = False

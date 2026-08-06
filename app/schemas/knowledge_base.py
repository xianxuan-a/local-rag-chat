"""Knowledge-base request and response schemas."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge_base import RebuildStatus
from app.core.retrieval_modes import KnowledgeBaseWebPolicy


class KnowledgeBaseCreate(BaseModel):
    """Payload used to create a knowledge base."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, description="知识库名称")
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="知识库说明",
    )
    web_access_policy: KnowledgeBaseWebPolicy = (
        KnowledgeBaseWebPolicy.INHERIT
    )

    @field_validator("description")
    @classmethod
    def empty_description_to_none(cls, value: str | None) -> str | None:
        """Treat an empty optional description as absent."""
        return value or None


class KnowledgeBaseUpdate(BaseModel):
    """Fields that may be changed without altering vector-space identity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    web_access_policy: KnowledgeBaseWebPolicy | None = None

    @field_validator("description")
    @classmethod
    def empty_description_to_none(cls, value: str | None) -> str | None:
        return value or None


class KnowledgeBaseResponse(BaseModel):
    """Public representation of a knowledge base."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    web_access_policy: KnowledgeBaseWebPolicy
    file_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    embedding_model: str
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any, *, embedding_model: str) -> Self:
        files = list(record.files)
        rebuild_status = (
            record.rebuild_status.value
            if isinstance(record.rebuild_status, RebuildStatus)
            else str(record.rebuild_status)
        )
        if rebuild_status == RebuildStatus.BUILDING.value:
            public_status = "BUILDING"
        elif rebuild_status == RebuildStatus.FAILED.value:
            public_status = "FAILED"
        elif not files:
            public_status = "EMPTY"
        else:
            public_status = "READY"
        return cls.model_validate(
            {
                "id": record.id,
                "owner_id": record.owner_id,
                "name": record.name,
                "description": record.description,
                "web_access_policy": record.web_access_policy,
                "file_count": len(files),
                "chunk_count": sum(item.chunk_count for item in files),
                "embedding_model": embedding_model,
                "status": public_status,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

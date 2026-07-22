"""Knowledge-base request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeBaseCreate(BaseModel):
    """Payload used to create a knowledge base."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, description="知识库名称")
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="知识库说明",
    )

    @field_validator("description")
    @classmethod
    def empty_description_to_none(cls, value: str | None) -> str | None:
        """Treat an empty optional description as absent."""
        return value or None


class KnowledgeBaseResponse(BaseModel):
    """Public representation of a knowledge base."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

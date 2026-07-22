"""RAG chat request and response schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """A question directed at one knowledge base."""

    model_config = ConfigDict(str_strip_whitespace=True)

    knowledge_base_id: UUID
    session_id: UUID | None = None
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=20)


class SourceReference(BaseModel):
    """Structured provenance for one retrieved chunk."""

    file_id: UUID
    file_name: str = Field(min_length=1, max_length=255)
    chunk_id: str = Field(min_length=1, max_length=100)
    content_preview: str = Field(max_length=1000)
    score: float = Field(ge=0.0, le=1.0)


class ChatResponse(BaseModel):
    """Answer text and its structured sources."""

    answer: str
    sources: list[SourceReference] = Field(default_factory=list)

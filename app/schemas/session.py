"""Chat-session request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import SourceReference
from app.core.retrieval_modes import RetrievalMode, WebSearchStatus


DEFAULT_SESSION_TITLE = "新会话"


class SessionCreate(BaseModel):
    """Payload for creating a chat session under one knowledge base."""

    model_config = ConfigDict(str_strip_whitespace=True)

    knowledge_base_id: UUID
    title: str = Field(default=DEFAULT_SESSION_TITLE, min_length=1, max_length=200)


class SessionResponse(BaseModel):
    """Public chat-session metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    title: str
    preview: str
    message_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class SessionUpdate(BaseModel):
    """Editable session metadata."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)


class MessageResponse(BaseModel):
    """Public representation of a persisted chat message."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    references: list[SourceReference] = Field(default_factory=list)
    status: Literal["complete", "streaming", "failed", "cancelled"]
    error_code: str | None = None
    error_message: str | None = None
    requested_mode: RetrievalMode | None = None
    effective_mode: RetrievalMode | None = None
    web_search_triggered: bool = False
    web_search_status: WebSearchStatus = WebSearchStatus.NOT_REQUESTED
    web_trigger_reason: str | None = None
    knowledge_source_count: int = Field(default=0, ge=0)
    web_source_count: int = Field(default=0, ge=0)
    fallback_reason: str | None = None
    reply_to_message_id: UUID | None = None
    feedback: Literal["like", "dislike"] | None = Field(
        default=None,
        validation_alias="feedback_value",
    )
    created_at: datetime
    updated_at: datetime


class FeedbackUpdate(BaseModel):
    """Idempotent feedback replacement; null clears the feedback."""

    value: Literal["like", "dislike"] | None


class FeedbackResponse(BaseModel):
    message_id: UUID
    value: Literal["like", "dislike"] | None
    updated_at: datetime | None = None

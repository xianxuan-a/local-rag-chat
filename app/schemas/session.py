"""Chat-session request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import SourceReference


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
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    """Public representation of a persisted chat message."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    references: list[SourceReference] = Field(default_factory=list)
    created_at: datetime

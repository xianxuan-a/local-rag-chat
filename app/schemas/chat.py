"""RAG chat request, response, provenance, and streaming schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.retrieval_modes import RetrievalMode, WebSearchStatus


class ChatRequest(BaseModel):
    """A question directed at one knowledge base."""

    model_config = ConfigDict(str_strip_whitespace=True)

    knowledge_base_id: UUID
    session_id: UUID | None = None
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    mode: RetrievalMode | None = None


class RetryChatRequest(BaseModel):
    """Retry one persisted assistant answer without adding another question."""

    knowledge_base_id: UUID
    session_id: UUID
    top_k: int | None = Field(default=None, ge=1, le=100)
    mode: RetrievalMode | None = None


class CancelChatRequest(BaseModel):
    """Request cooperative cancellation for one active streamed answer."""

    knowledge_base_id: UUID
    session_id: UUID


class CancelChatResponse(BaseModel):
    """Acknowledge that the exact active answer received a stop signal."""

    session_id: UUID
    assistant_message_id: UUID
    cancel_requested: bool


class SourceReference(BaseModel):
    """Structured provenance for a local chunk or fetched web page."""

    model_config = ConfigDict(str_strip_whitespace=True)

    citation_number: int = Field(default=1, ge=1)
    source_type: Literal["knowledge_base", "web"] = "knowledge_base"
    reference: str | None = Field(default=None, max_length=16)
    title: str | None = Field(default=None, max_length=500)
    file_id: UUID | None = None
    file_name: str | None = Field(default=None, max_length=255)
    chunk_id: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=2048)
    domain: str | None = Field(default=None, max_length=253)
    published_at: datetime | None = None
    accessed_at: datetime | None = None
    content_preview: str = Field(max_length=1000)
    score: float = Field(ge=-1.0, le=1.0)
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )

    @field_validator("url")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("网页来源 URL 必须是公开 HTTP/HTTPS 地址")
        return value

    @model_validator(mode="after")
    def validate_source_shape(self) -> "SourceReference":
        prefix = "K" if self.source_type == "knowledge_base" else "W"
        expected_reference = f"[{prefix}{self.citation_number}]"
        if self.reference is None:
            self.reference = expected_reference
        if self.reference != expected_reference:
            raise ValueError("来源 reference 与类型或编号不一致")
        if self.source_type == "knowledge_base":
            if self.file_id is None or not self.file_name or not self.chunk_id:
                raise ValueError("知识库来源缺少文件或分块标识")
            if self.title is None:
                self.title = self.file_name
        else:
            if not self.url or not self.domain:
                raise ValueError("网页来源缺少 URL 或域名")
            if self.title is None:
                self.title = self.domain
        return self


class RetrievalAudit(BaseModel):
    """Public, persistable summary of the retrieval decision."""

    requested_mode: RetrievalMode = RetrievalMode.KNOWLEDGE_ONLY
    effective_mode: RetrievalMode = RetrievalMode.KNOWLEDGE_ONLY
    web_search_triggered: bool = False
    web_search_status: WebSearchStatus = WebSearchStatus.NOT_REQUESTED
    web_trigger_reason: str | None = Field(default=None, max_length=64)
    knowledge_source_count: int = Field(default=0, ge=0)
    web_source_count: int = Field(default=0, ge=0)
    fallback_reason: str | None = Field(default=None, max_length=128)


class ChatResponse(RetrievalAudit):
    """Answer text and its structured sources."""

    session_id: UUID | None = None
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    answer: str
    sources: list[SourceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def synchronize_source_counts(self) -> "ChatResponse":
        knowledge_count = sum(
            source.source_type == "knowledge_base"
            for source in self.sources
        )
        web_count = sum(source.source_type == "web" for source in self.sources)
        if self.knowledge_source_count == 0 and knowledge_count:
            self.knowledge_source_count = knowledge_count
        if self.web_source_count == 0 and web_count:
            self.web_source_count = web_count
        return self


class ChatStreamEvent(RetrievalAudit):
    """One structured event in the NDJSON streaming chat protocol."""

    type: Literal[
        "start",
        "retrieval",
        "delta",
        "sources",
        "done",
        "error",
    ]
    session_id: UUID | None = None
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    retry: bool | None = None
    content: str | None = None
    sources: list[SourceReference] | None = None
    message_id: UUID | None = None
    message: str | None = None
    code: int | None = None
    error_code: str | None = None

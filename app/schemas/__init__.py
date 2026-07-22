"""Pydantic request and response contracts."""

from app.schemas.chat import ChatRequest, ChatResponse, SourceReference
from app.schemas.file import FileRecordResponse, FileStatusResponse, FileUploadResponse
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseResponse
from app.schemas.session import MessageResponse, SessionCreate, SessionResponse

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "FileRecordResponse",
    "FileStatusResponse",
    "FileUploadResponse",
    "KnowledgeBaseCreate",
    "KnowledgeBaseResponse",
    "MessageResponse",
    "SessionCreate",
    "SessionResponse",
    "SourceReference",
]

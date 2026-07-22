"""SQLAlchemy model exports.

Importing every model here ensures relationship targets are registered before
``Base.metadata.create_all`` configures the mappings.
"""

from app.models.base import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
    new_uuid,
    utc_now,
)
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.file_record import FileRecord, FileStatus
from app.models.knowledge_base import KnowledgeBase

__all__ = [
    "Base",
    "ChatMessage",
    "ChatSession",
    "FileRecord",
    "FileStatus",
    "KnowledgeBase",
    "MessageRole",
    "TimestampMixin",
    "UTCDateTime",
    "UUIDPrimaryKeyMixin",
    "new_uuid",
    "utc_now",
]

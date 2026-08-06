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
from app.models.chat_message import ChatMessage, MessageRole, MessageStatus
from app.models.chat_session import ChatSession
from app.models.file_record import FileRecord, FileStatus
from app.models.evaluation_dataset import EvaluationDataset
from app.models.knowledge_base import KnowledgeBase, RebuildStatus
from app.models.job import (
    Job,
    JobStatus,
    JobType,
    NON_TERMINAL_JOB_STATUSES,
    RuntimeState,
    TERMINAL_JOB_STATUSES,
)
from app.models.user import User, UserRole
from app.models.product_settings import ProductSettings
from app.models.message_feedback import FeedbackValue, MessageFeedback

__all__ = [
    "Base",
    "ChatMessage",
    "ChatSession",
    "FileRecord",
    "FileStatus",
    "EvaluationDataset",
    "KnowledgeBase",
    "Job",
    "JobStatus",
    "JobType",
    "NON_TERMINAL_JOB_STATUSES",
    "RuntimeState",
    "ProductSettings",
    "TERMINAL_JOB_STATUSES",
    "RebuildStatus",
    "MessageRole",
    "MessageStatus",
    "FeedbackValue",
    "MessageFeedback",
    "TimestampMixin",
    "UTCDateTime",
    "User",
    "UserRole",
    "UUIDPrimaryKeyMixin",
    "new_uuid",
    "utc_now",
]

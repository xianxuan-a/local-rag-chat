"""Chat-history API skeleton."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.exceptions import FeatureNotImplementedException
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat import SourceReference
from app.schemas.session import SessionCreate


class ChatHistoryService:
    """Expose typed session operations while persistence remains out of scope."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(self, payload: SessionCreate) -> ChatSession:
        _ = payload
        raise FeatureNotImplementedException("会话创建功能尚未完成初始化")

    def list_sessions(self, knowledge_base_id: str) -> list[ChatSession]:
        _ = knowledge_base_id
        raise FeatureNotImplementedException("会话列表功能尚未完成初始化")

    def get_session(self, session_id: str) -> ChatSession:
        _ = session_id
        raise FeatureNotImplementedException("会话查询功能尚未完成初始化")

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        references: Sequence[SourceReference] | None = None,
    ) -> ChatMessage:
        _ = (session_id, role, content, references)
        raise FeatureNotImplementedException("消息保存功能尚未完成初始化")

    def get_messages(self, session_id: str) -> list[ChatMessage]:
        _ = session_id
        raise FeatureNotImplementedException("消息查询功能尚未完成初始化")

    def delete_session(self, session_id: str) -> ChatSession:
        _ = session_id
        raise FeatureNotImplementedException("会话删除功能尚未完成初始化")

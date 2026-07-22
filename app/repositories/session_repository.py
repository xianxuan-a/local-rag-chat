"""Typed persistence contract for chat sessions and messages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import FeatureNotImplementedException
from app.models import ChatMessage, ChatSession, MessageRole


class SessionRepository:
    """Reserve session persistence operations for the later chat phase."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(
        self, knowledge_base_id: str, title: str
    ) -> ChatSession:
        _ = (knowledge_base_id, title)
        raise FeatureNotImplementedException("会话创建功能尚未完成初始化")

    def get_session(self, session_id: str) -> ChatSession | None:
        _ = session_id
        raise FeatureNotImplementedException("会话查询功能尚未完成初始化")

    def list_sessions(
        self, knowledge_base_id: str | None = None
    ) -> list[ChatSession]:
        _ = knowledge_base_id
        raise FeatureNotImplementedException("会话列表功能尚未完成初始化")

    def save_message(
        self,
        session_id: str,
        role: MessageRole | str,
        content: str,
        references: Sequence[dict[str, Any]] | None = None,
    ) -> ChatMessage:
        _ = (session_id, role, content, references)
        raise FeatureNotImplementedException("消息保存功能尚未完成初始化")

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        _ = session_id
        raise FeatureNotImplementedException("消息列表功能尚未完成初始化")

    def delete_session(self, chat_session: ChatSession) -> ChatSession:
        _ = chat_session
        raise FeatureNotImplementedException("会话删除功能尚未完成初始化")

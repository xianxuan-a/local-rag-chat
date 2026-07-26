"""Data-access operations for chat sessions and messages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, MessageRole
from app.models.base import utc_now


class SessionRepository:
    """Persist chat history without owning transaction boundaries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(
        self, knowledge_base_id: str, title: str
    ) -> ChatSession:
        chat_session = ChatSession(
            knowledge_base_id=str(knowledge_base_id),
            title=title,
        )
        self.db.add(chat_session)
        self.db.flush()
        self.db.refresh(chat_session)
        return chat_session

    def get_session(self, session_id: str) -> ChatSession | None:
        statement = select(ChatSession).where(
            ChatSession.id == str(session_id)
        )
        return self.db.scalar(statement)

    def list_sessions(
        self, knowledge_base_id: str
    ) -> list[ChatSession]:
        statement = (
            select(ChatSession)
            .where(
                ChatSession.knowledge_base_id == str(knowledge_base_id)
            )
            .order_by(
                ChatSession.updated_at.desc(),
                ChatSession.id.desc(),
            )
        )
        return list(self.db.scalars(statement).all())

    def save_message(
        self,
        session_id: str,
        role: MessageRole | str,
        content: str,
        references: Sequence[dict[str, Any]] | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=str(session_id),
            role=role if isinstance(role, MessageRole) else MessageRole(role),
            content=content,
            references=list(references or ()),
        )
        self.db.add(message)
        self.db.flush()
        self.db.refresh(message)
        return message

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == str(session_id))
            .order_by(
                ChatMessage.created_at.asc(),
                ChatMessage.id.asc(),
            )
        )
        return list(self.db.scalars(statement).all())

    def update_activity(
        self,
        chat_session: ChatSession,
        *,
        title: str | None = None,
    ) -> ChatSession:
        if title is not None:
            chat_session.title = title
        chat_session.updated_at = utc_now()
        self.db.flush()
        self.db.refresh(chat_session)
        return chat_session

    def delete_messages(self, session_id: str) -> int:
        statement = delete(ChatMessage).where(
            ChatMessage.session_id == str(session_id)
        )
        result = self.db.execute(statement)
        self.db.flush()
        return int(result.rowcount or 0)

    def delete_session(self, chat_session: ChatSession) -> ChatSession:
        self.db.delete(chat_session)
        self.db.flush()
        return chat_session

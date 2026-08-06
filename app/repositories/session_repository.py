"""Data-access operations for chat sessions, messages, and feedback."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ChatMessage,
    ChatSession,
    FeedbackValue,
    KnowledgeBase,
    MessageFeedback,
    MessageRole,
    MessageStatus,
)
from app.models.base import utc_now


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: str
    knowledge_base_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str


class SessionRepository:
    """Persist chat history without owning transaction boundaries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(self, knowledge_base_id: str, title: str) -> ChatSession:
        chat_session = ChatSession(
            knowledge_base_id=str(knowledge_base_id),
            title=title,
        )
        self.db.add(chat_session)
        self.db.flush()
        self.db.refresh(chat_session)
        return chat_session

    def get_session(self, session_id: str) -> ChatSession | None:
        return self.db.scalar(
            select(ChatSession).where(ChatSession.id == str(session_id))
        )

    def summarize_session(self, chat_session: ChatSession) -> SessionSummary:
        summaries = self._summary_statement(
            select(ChatSession).where(ChatSession.id == chat_session.id)
        )
        if not summaries:
            raise LookupError(f"session disappeared: {chat_session.id}")
        return summaries[0]

    def list_sessions(
        self,
        *,
        knowledge_base_id: str | None,
        owner_id: str | None,
        limit: int,
        offset: int,
    ) -> list[SessionSummary]:
        statement = select(ChatSession)
        if owner_id is not None:
            statement = statement.join(
                KnowledgeBase,
                KnowledgeBase.id == ChatSession.knowledge_base_id,
            ).where(KnowledgeBase.owner_id == owner_id)
        if knowledge_base_id is not None:
            statement = statement.where(
                ChatSession.knowledge_base_id == str(knowledge_base_id)
            )
        statement = statement.order_by(
            ChatSession.updated_at.desc(),
            ChatSession.id.desc(),
        ).limit(limit).offset(offset)
        return self._summary_statement(statement)

    def _summary_statement(self, statement):
        message_count = (
            select(func.count(ChatMessage.id))
            .where(ChatMessage.session_id == ChatSession.id)
            .correlate(ChatSession)
            .scalar_subquery()
        )
        latest_content = (
            select(
                func.coalesce(
                    func.nullif(ChatMessage.content, ""),
                    ChatMessage.error_message,
                )
            )
            .where(ChatMessage.session_id == ChatSession.id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
            .correlate(ChatSession)
            .scalar_subquery()
        )
        rows = self.db.execute(
            statement.add_columns(
                message_count.label("message_count"),
                latest_content.label("preview"),
            )
        )
        summaries: list[SessionSummary] = []
        for chat_session, count, preview in rows:
            summaries.append(
                SessionSummary(
                    id=chat_session.id,
                    knowledge_base_id=chat_session.knowledge_base_id,
                    title=chat_session.title,
                    created_at=chat_session.created_at,
                    updated_at=chat_session.updated_at,
                    message_count=int(count or 0),
                    preview=str(preview or "尚未开始对话")[:200],
                )
            )
        return summaries

    def save_message(
        self,
        session_id: str,
        role: MessageRole | str,
        content: str,
        references: Sequence[dict[str, Any]] | None = None,
        *,
        status: MessageStatus | str = MessageStatus.COMPLETE,
        error_code: str | None = None,
        error_message: str | None = None,
        reply_to_message_id: str | None = None,
        requested_mode: str | None = None,
        effective_mode: str | None = None,
        web_search_triggered: bool = False,
        web_search_status: str = "not_requested",
        web_trigger_reason: str | None = None,
        knowledge_source_count: int = 0,
        web_source_count: int = 0,
        fallback_reason: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=str(session_id),
            role=role if isinstance(role, MessageRole) else MessageRole(role),
            content=content,
            references=list(references or ()),
            status=(
                status
                if isinstance(status, MessageStatus)
                else MessageStatus(status)
            ),
            error_code=error_code,
            error_message=error_message,
            reply_to_message_id=reply_to_message_id,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            web_search_triggered=web_search_triggered,
            web_search_status=web_search_status,
            web_trigger_reason=web_trigger_reason,
            knowledge_source_count=knowledge_source_count,
            web_source_count=web_source_count,
            fallback_reason=fallback_reason,
        )
        self.db.add(message)
        self.db.flush()
        self.db.refresh(message)
        return message

    def get_message(self, message_id: str) -> ChatMessage | None:
        return self.db.scalar(
            select(ChatMessage)
            .options(selectinload(ChatMessage.feedback))
            .where(ChatMessage.id == str(message_id))
        )

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[ChatMessage]:
        statement = (
            select(ChatMessage)
            .options(selectinload(ChatMessage.feedback))
            .where(ChatMessage.session_id == str(session_id))
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement).all())

    def count_messages(self, session_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.session_id == str(session_id)
                )
            )
            or 0
        )

    def update_message(
        self,
        message: ChatMessage,
        *,
        content: str | None = None,
        references: Sequence[dict[str, Any]] | None = None,
        status: MessageStatus | str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        requested_mode: str | None = None,
        effective_mode: str | None = None,
        web_search_triggered: bool | None = None,
        web_search_status: str | None = None,
        web_trigger_reason: str | None = None,
        knowledge_source_count: int | None = None,
        web_source_count: int | None = None,
        fallback_reason: str | None = None,
        update_retrieval_audit: bool = False,
    ) -> ChatMessage:
        if content is not None:
            message.content = content
        if references is not None:
            message.references = list(references)
        if status is not None:
            message.status = (
                status
                if isinstance(status, MessageStatus)
                else MessageStatus(status)
            )
        message.error_code = error_code
        message.error_message = error_message
        if update_retrieval_audit:
            message.requested_mode = requested_mode
            message.effective_mode = effective_mode
            if web_search_triggered is not None:
                message.web_search_triggered = web_search_triggered
            if web_search_status is not None:
                message.web_search_status = web_search_status
            message.web_trigger_reason = web_trigger_reason
            if knowledge_source_count is not None:
                message.knowledge_source_count = knowledge_source_count
            if web_source_count is not None:
                message.web_source_count = web_source_count
            message.fallback_reason = fallback_reason
        message.updated_at = utc_now()
        self.db.flush()
        self.db.refresh(message)
        return message

    def resolve_reply_user(self, assistant: ChatMessage) -> ChatMessage | None:
        if assistant.reply_to_message_id:
            message = self.get_message(assistant.reply_to_message_id)
            if message is not None and message.role == MessageRole.USER:
                return message
        preceding = self.db.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == assistant.session_id,
                ChatMessage.role == MessageRole.USER,
                (
                    (ChatMessage.created_at < assistant.created_at)
                    | (
                        (ChatMessage.created_at == assistant.created_at)
                        & (ChatMessage.id < assistant.id)
                    )
                ),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        if preceding is None:
            return None
        already_used = self.db.scalar(
            select(ChatMessage.id).where(
                ChatMessage.reply_to_message_id == preceding.id,
                ChatMessage.id != assistant.id,
            )
        )
        if already_used is not None:
            return None
        assistant.reply_to_message_id = preceding.id
        self.db.flush()
        return preceding

    def set_feedback(
        self,
        message: ChatMessage,
        value: FeedbackValue | str,
        updated_by_id: str | None,
    ) -> MessageFeedback:
        resolved = value if isinstance(value, FeedbackValue) else FeedbackValue(value)
        feedback = message.feedback
        if feedback is None:
            feedback = MessageFeedback(
                message_id=message.id,
                value=resolved.value,
                updated_by_id=updated_by_id,
            )
            self.db.add(feedback)
        else:
            feedback.value = resolved.value
            feedback.updated_by_id = updated_by_id
            feedback.updated_at = utc_now()
        self.db.flush()
        self.db.refresh(feedback)
        message.feedback = feedback
        return feedback

    def clear_feedback(self, message: ChatMessage) -> None:
        if message.feedback is None:
            return
        self.db.delete(message.feedback)
        self.db.flush()
        message.feedback = None

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
        result = self.db.execute(
            delete(ChatMessage).where(
                ChatMessage.session_id == str(session_id)
            )
        )
        self.db.flush()
        return int(result.rowcount or 0)

    def delete_session(self, chat_session: ChatSession) -> ChatSession:
        self.db.delete(chat_session)
        self.db.flush()
        return chat_session

    def recover_streaming_messages(self) -> int:
        result = self.db.execute(
            update(ChatMessage)
            .where(ChatMessage.status == MessageStatus.STREAMING)
            .values(
                status=MessageStatus.FAILED,
                error_code="ORPHANED_STREAMING_MESSAGE",
                error_message="服务重启，未完成的流式回答已标记失败",
                updated_at=utc_now(),
            )
        )
        self.db.flush()
        return int(result.rowcount or 0)

"""Chat-session ownership, lifecycle persistence, and transactions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ResourceNotFoundException,
    ValidationException,
)
from app.models import (
    ChatMessage,
    ChatSession,
    FeedbackValue,
    JobType,
    MessageRole,
    MessageStatus,
    RebuildStatus,
)
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.job_repository import JobRepository
from app.repositories.session_repository import SessionRepository, SessionSummary
from app.schemas.chat import ChatResponse, RetrievalAudit, SourceReference
from app.core.retrieval_modes import RetrievalMode
from app.schemas.session import DEFAULT_SESSION_TITLE, SessionCreate


@dataclass(frozen=True, slots=True)
class ChatTurn:
    session: ChatSession
    user_message: ChatMessage
    assistant_message: ChatMessage


@dataclass(frozen=True, slots=True)
class RetryTurn:
    session: ChatSession
    user_message: ChatMessage
    assistant_message: ChatMessage
    original_status: MessageStatus


class ChatHistoryService:
    """Own chat-history business rules and transaction boundaries."""

    def __init__(self, db: Session, owner_id: str | None = None) -> None:
        self.db = db
        self.owner_id = owner_id
        self.sessions = SessionRepository(db)
        self.knowledge_bases = KnowledgeBaseRepository(db)
        self.jobs = JobRepository(db)

    def create_session(self, payload: SessionCreate) -> SessionSummary:
        self._get_writable_knowledge_base(str(payload.knowledge_base_id))
        try:
            chat_session = self.sessions.create_session(
                str(payload.knowledge_base_id),
                payload.title,
            )
            self.db.commit()
            return self.sessions.summarize_session(chat_session)
        except Exception:
            self.db.rollback()
            raise

    def list_sessions(
        self,
        knowledge_base_id: str | None,
        *,
        limit: int,
        offset: int,
    ) -> list[SessionSummary]:
        if knowledge_base_id is not None:
            self._get_knowledge_base(knowledge_base_id)
        return self.sessions.list_sessions(
            knowledge_base_id=knowledge_base_id,
            owner_id=self.owner_id,
            limit=limit,
            offset=offset,
        )

    def get_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> ChatSession:
        self._get_knowledge_base(knowledge_base_id)
        return self._get_owned_session(knowledge_base_id, session_id)

    def get_session_summary(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> SessionSummary:
        return self.sessions.summarize_session(
            self.get_session(knowledge_base_id, session_id)
        )

    def update_session_title(
        self,
        knowledge_base_id: str,
        session_id: str,
        title: str,
    ) -> SessionSummary:
        self._get_writable_knowledge_base(knowledge_base_id)
        chat_session = self._get_owned_session(knowledge_base_id, session_id)
        resolved = title.strip()
        if not resolved:
            raise ValidationException("会话标题不能为空")
        try:
            self.sessions.update_activity(chat_session, title=resolved[:200])
            self.db.commit()
            return self.sessions.summarize_session(chat_session)
        except Exception:
            self.db.rollback()
            raise

    def start_turn(
        self,
        knowledge_base_id: str,
        session_id: str | None,
        question: str,
        requested_mode: RetrievalMode | str = RetrievalMode.KNOWLEDGE_ONLY,
    ) -> ChatTurn:
        self._get_writable_knowledge_base(knowledge_base_id)
        normalized_question = question.strip()
        if not normalized_question:
            raise ValidationException("question 不能为空")
        try:
            if session_id is None:
                chat_session = self.sessions.create_session(
                    knowledge_base_id,
                    normalized_question[:200],
                )
            else:
                chat_session = self._get_owned_session(
                    knowledge_base_id,
                    session_id,
                )
            title = None
            if (
                chat_session.title == DEFAULT_SESSION_TITLE
                and self.sessions.count_messages(chat_session.id) == 0
            ):
                title = normalized_question[:200]
            user_message = self.sessions.save_message(
                chat_session.id,
                MessageRole.USER,
                normalized_question,
                status=MessageStatus.COMPLETE,
            )
            assistant_message = self.sessions.save_message(
                chat_session.id,
                MessageRole.ASSISTANT,
                "",
                status=MessageStatus.STREAMING,
                reply_to_message_id=user_message.id,
                requested_mode=(
                    requested_mode.value
                    if isinstance(requested_mode, RetrievalMode)
                    else str(requested_mode)
                ),
            )
            self.sessions.update_activity(chat_session, title=title)
            self.db.commit()
            return ChatTurn(chat_session, user_message, assistant_message)
        except Exception:
            self.db.rollback()
            raise

    def complete_turn(
        self,
        knowledge_base_id: str,
        turn: ChatTurn,
        response: ChatResponse,
    ) -> ChatMessage:
        return self._finish_assistant(
            knowledge_base_id,
            turn.session.id,
            turn.assistant_message.id,
            content=response.answer,
            references=response.sources,
            status=MessageStatus.COMPLETE,
            error_code=None,
            error_message=None,
            retrieval_audit=response,
        )

    def record_retrieval_audit(
        self,
        knowledge_base_id: str,
        session_id: str,
        assistant_message_id: str,
        audit: RetrievalAudit,
    ) -> ChatMessage:
        """Persist the resolved retrieval decision before generation starts."""

        self._get_writable_knowledge_base(knowledge_base_id)
        chat_session = self._get_owned_session(
            knowledge_base_id,
            session_id,
        )
        assistant = self._get_owned_message(
            chat_session.id,
            assistant_message_id,
        )
        try:
            self.sessions.update_message(
                assistant,
                requested_mode=audit.requested_mode.value,
                effective_mode=audit.effective_mode.value,
                web_search_triggered=audit.web_search_triggered,
                web_search_status=audit.web_search_status.value,
                web_trigger_reason=audit.web_trigger_reason,
                knowledge_source_count=audit.knowledge_source_count,
                web_source_count=audit.web_source_count,
                fallback_reason=audit.fallback_reason,
                update_retrieval_audit=True,
            )
            self.db.commit()
            return assistant
        except Exception:
            self.db.rollback()
            raise

    def fail_turn(
        self,
        knowledge_base_id: str,
        turn: ChatTurn,
        *,
        partial_content: str,
        error_code: str,
        error_message: str,
    ) -> ChatMessage:
        return self._finish_assistant(
            knowledge_base_id,
            turn.session.id,
            turn.assistant_message.id,
            content=partial_content,
            references=(),
            status=MessageStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )

    def cancel_turn(
        self,
        knowledge_base_id: str,
        turn: ChatTurn,
        *,
        partial_content: str,
    ) -> ChatMessage:
        return self._finish_assistant(
            knowledge_base_id,
            turn.session.id,
            turn.assistant_message.id,
            content=partial_content,
            references=(),
            status=MessageStatus.CANCELLED,
            error_code="CLIENT_DISCONNECTED",
            error_message="客户端已停止或流式连接中断",
        )

    def validate_cancel_target(
        self,
        knowledge_base_id: str,
        session_id: str,
        assistant_message_id: str,
    ) -> ChatMessage:
        """Authorize a stop request and return its exact assistant message."""

        self._get_knowledge_base(knowledge_base_id)
        chat_session = self._get_owned_session(knowledge_base_id, session_id)
        assistant = self._get_owned_message(
            chat_session.id,
            assistant_message_id,
        )
        if assistant.role != MessageRole.ASSISTANT:
            raise ResourceNotFoundException("助手回答不存在或不属于该会话")
        if assistant.status not in (
            MessageStatus.STREAMING,
            MessageStatus.CANCELLED,
        ):
            raise ConflictException("该回答已结束，不能停止")
        return assistant

    def prepare_retry(
        self,
        knowledge_base_id: str,
        session_id: str,
        assistant_message_id: str,
        requested_mode: RetrievalMode | str = RetrievalMode.KNOWLEDGE_ONLY,
    ) -> RetryTurn:
        self._get_writable_knowledge_base(knowledge_base_id)
        chat_session = self._get_owned_session(knowledge_base_id, session_id)
        assistant = self.sessions.get_message(assistant_message_id)
        if (
            assistant is None
            or assistant.session_id != chat_session.id
            or assistant.role != MessageRole.ASSISTANT
        ):
            raise ResourceNotFoundException("助手回答不存在或不属于该会话")
        if assistant.status == MessageStatus.STREAMING:
            raise ConflictException("当前回答仍在生成，不能重试")
        original_status = MessageStatus(assistant.status)
        try:
            user_message = self.sessions.resolve_reply_user(assistant)
            if user_message is None:
                raise ConflictException("无法确定该回答对应的用户问题")
            self.sessions.update_message(
                assistant,
                requested_mode=(
                    requested_mode.value
                    if isinstance(requested_mode, RetrievalMode)
                    else str(requested_mode)
                ),
                effective_mode=None,
                web_search_triggered=False,
                web_search_status="not_requested",
                web_trigger_reason=None,
                knowledge_source_count=0,
                web_source_count=0,
                fallback_reason=None,
                update_retrieval_audit=True,
            )
            self.db.commit()
            return RetryTurn(
                chat_session,
                user_message,
                assistant,
                original_status,
            )
        except Exception:
            self.db.rollback()
            raise

    def complete_retry(
        self,
        knowledge_base_id: str,
        retry: RetryTurn,
        response: ChatResponse,
    ) -> ChatMessage:
        self._get_writable_knowledge_base(knowledge_base_id)
        assistant = self._get_owned_message(
            retry.session.id,
            retry.assistant_message.id,
        )
        try:
            self.sessions.update_message(
                assistant,
                content=response.answer,
                references=self._serialize_references(response.sources),
                status=MessageStatus.COMPLETE,
                error_code=None,
                error_message=None,
                requested_mode=response.requested_mode.value,
                effective_mode=response.effective_mode.value,
                web_search_triggered=response.web_search_triggered,
                web_search_status=response.web_search_status.value,
                web_trigger_reason=response.web_trigger_reason,
                knowledge_source_count=response.knowledge_source_count,
                web_source_count=response.web_source_count,
                fallback_reason=response.fallback_reason,
                update_retrieval_audit=True,
            )
            self.sessions.clear_feedback(assistant)
            self.sessions.update_activity(retry.session)
            self.db.commit()
            return assistant
        except Exception:
            self.db.rollback()
            raise

    def fail_retry(
        self,
        knowledge_base_id: str,
        retry: RetryTurn,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        if retry.original_status == MessageStatus.COMPLETE:
            self.db.rollback()
            return
        assistant = self._get_owned_message(
            retry.session.id,
            retry.assistant_message.id,
        )
        try:
            self.sessions.update_message(
                assistant,
                status=retry.original_status,
                error_code=error_code,
                error_message=error_message,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def get_messages(
        self,
        knowledge_base_id: str,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[ChatMessage]:
        chat_session = self.get_session(knowledge_base_id, session_id)
        return self.sessions.list_messages(
            chat_session.id,
            limit=limit,
            offset=offset,
        )

    def update_feedback(
        self,
        knowledge_base_id: str,
        session_id: str,
        message_id: str,
        value: FeedbackValue | str | None,
        *,
        updated_by_id: str | None,
    ) -> ChatMessage:
        self._get_writable_knowledge_base(knowledge_base_id)
        chat_session = self._get_owned_session(knowledge_base_id, session_id)
        message = self._get_owned_message(chat_session.id, message_id)
        if (
            message.role != MessageRole.ASSISTANT
            or message.status != MessageStatus.COMPLETE
        ):
            raise ConflictException("仅能评价已完成的助手回答")
        try:
            if value is None:
                self.sessions.clear_feedback(message)
            else:
                self.sessions.set_feedback(message, value, updated_by_id)
            self.db.commit()
            return self.sessions.get_message(message.id) or message
        except Exception:
            self.db.rollback()
            raise

    def delete_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> SessionSummary:
        self._get_writable_knowledge_base(knowledge_base_id)
        chat_session = self.get_session(knowledge_base_id, session_id)
        summary = self.sessions.summarize_session(chat_session)
        try:
            self.sessions.delete_messages(chat_session.id)
            self.sessions.delete_session(chat_session)
            self.db.commit()
            return summary
        except Exception:
            self.db.rollback()
            raise

    def recover_incomplete_messages(self) -> int:
        try:
            recovered = self.sessions.recover_streaming_messages()
            self.db.commit()
            return recovered
        except Exception:
            self.db.rollback()
            raise

    def _finish_assistant(
        self,
        knowledge_base_id: str,
        session_id: str,
        assistant_message_id: str,
        *,
        content: str,
        references: Sequence[SourceReference],
        status: MessageStatus,
        error_code: str | None,
        error_message: str | None,
        retrieval_audit: RetrievalAudit | None = None,
    ) -> ChatMessage:
        self._get_writable_knowledge_base(knowledge_base_id)
        chat_session = self._get_owned_session(knowledge_base_id, session_id)
        assistant = self._get_owned_message(
            chat_session.id,
            assistant_message_id,
        )
        try:
            self.sessions.update_message(
                assistant,
                content=content,
                references=self._serialize_references(references),
                status=status,
                error_code=error_code,
                error_message=error_message,
                requested_mode=(
                    retrieval_audit.requested_mode.value
                    if retrieval_audit is not None
                    else None
                ),
                effective_mode=(
                    retrieval_audit.effective_mode.value
                    if retrieval_audit is not None
                    else None
                ),
                web_search_triggered=(
                    retrieval_audit.web_search_triggered
                    if retrieval_audit is not None
                    else None
                ),
                web_search_status=(
                    retrieval_audit.web_search_status.value
                    if retrieval_audit is not None
                    else None
                ),
                web_trigger_reason=(
                    retrieval_audit.web_trigger_reason
                    if retrieval_audit is not None
                    else None
                ),
                knowledge_source_count=(
                    retrieval_audit.knowledge_source_count
                    if retrieval_audit is not None
                    else None
                ),
                web_source_count=(
                    retrieval_audit.web_source_count
                    if retrieval_audit is not None
                    else None
                ),
                fallback_reason=(
                    retrieval_audit.fallback_reason
                    if retrieval_audit is not None
                    else None
                ),
                update_retrieval_audit=retrieval_audit is not None,
            )
            self.sessions.update_activity(chat_session)
            self.db.commit()
            return assistant
        except Exception:
            self.db.rollback()
            raise

    def _get_knowledge_base(self, knowledge_base_id: str):
        knowledge_base = self.knowledge_bases.get_by_id(
            knowledge_base_id,
            self.owner_id,
        )
        if knowledge_base is None:
            raise ResourceNotFoundException("知识库不存在")
        return knowledge_base

    def _get_writable_knowledge_base(self, knowledge_base_id: str):
        knowledge_base = self._get_knowledge_base(knowledge_base_id)
        if knowledge_base.rebuild_status is RebuildStatus.BUILDING:
            raise ConflictException(
                "知识库正在重建，暂时拒绝会话或聊天历史写入"
            )
        if self.jobs.has_nonterminal_knowledge_base_job(
            knowledge_base.id,
            job_types=(JobType.KB_REBUILD,),
        ):
            raise ConflictException(
                "知识库重建 Job 已排队或运行，暂时拒绝会话或聊天历史写入"
            )
        return knowledge_base

    def _get_owned_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> ChatSession:
        chat_session = self.sessions.get_session(session_id)
        if (
            chat_session is None
            or chat_session.knowledge_base_id != str(knowledge_base_id)
        ):
            raise ResourceNotFoundException("会话不存在或不属于该知识库")
        return chat_session

    def _get_owned_message(
        self,
        session_id: str,
        message_id: str,
    ) -> ChatMessage:
        message = self.sessions.get_message(message_id)
        if message is None or message.session_id != session_id:
            raise ResourceNotFoundException("消息不存在或不属于该会话")
        return message

    @staticmethod
    def _serialize_references(
        references: Sequence[SourceReference] | None,
    ) -> list[dict[str, object]]:
        return [
            reference.model_dump(mode="json")
            for reference in (references or ())
        ]

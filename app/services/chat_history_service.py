"""Chat-session ownership, persistence, and transaction orchestration."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundException
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.chat import ChatResponse
from app.schemas.chat import SourceReference
from app.schemas.session import DEFAULT_SESSION_TITLE, SessionCreate


class ChatHistoryService:
    """Own chat-history business rules and database transaction boundaries."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.knowledge_bases = KnowledgeBaseRepository(db)

    def create_session(self, payload: SessionCreate) -> ChatSession:
        self._get_knowledge_base(str(payload.knowledge_base_id))
        try:
            chat_session = self.sessions.create_session(
                str(payload.knowledge_base_id),
                payload.title,
            )
            self.db.commit()
            return chat_session
        except Exception:
            self.db.rollback()
            raise

    def list_sessions(self, knowledge_base_id: str) -> list[ChatSession]:
        self._get_knowledge_base(knowledge_base_id)
        return self.sessions.list_sessions(knowledge_base_id)

    def get_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> ChatSession:
        self._get_knowledge_base(knowledge_base_id)
        return self._get_owned_session(knowledge_base_id, session_id)

    def prepare_session_for_chat(
        self,
        knowledge_base_id: str,
        session_id: str | None,
        question: str,
    ) -> ChatSession:
        """Validate an existing session or create a committed first session."""

        self._get_knowledge_base(knowledge_base_id)
        if session_id is not None:
            return self._get_owned_session(knowledge_base_id, session_id)

        title = question.strip()[:200] or DEFAULT_SESSION_TITLE
        try:
            chat_session = self.sessions.create_session(
                knowledge_base_id,
                title,
            )
            self.db.commit()
            return chat_session
        except Exception:
            self.db.rollback()
            raise

    def save_message(
        self,
        knowledge_base_id: str,
        session_id: str,
        role: MessageRole | str,
        content: str,
        references: Sequence[SourceReference] | None = None,
    ) -> ChatMessage:
        chat_session = self._get_owned_session(
            knowledge_base_id,
            session_id,
        )
        try:
            message = self.sessions.save_message(
                chat_session.id,
                role,
                content,
                self._serialize_references(references),
            )
            self.sessions.update_activity(chat_session)
            self.db.commit()
            return message
        except Exception:
            self.db.rollback()
            raise

    def save_exchange(
        self,
        knowledge_base_id: str,
        session_id: str,
        question: str,
        response: ChatResponse,
    ) -> tuple[ChatMessage, ChatMessage]:
        """Atomically persist one successful user/assistant exchange."""

        chat_session = self._get_owned_session(
            knowledge_base_id,
            session_id,
        )
        existing_messages = self.sessions.list_messages(chat_session.id)
        title = None
        if not existing_messages and chat_session.title == DEFAULT_SESSION_TITLE:
            title = question.strip()[:200] or DEFAULT_SESSION_TITLE

        try:
            user_message = self.sessions.save_message(
                chat_session.id,
                MessageRole.USER,
                question,
            )
            assistant_message = self.sessions.save_message(
                chat_session.id,
                MessageRole.ASSISTANT,
                response.answer,
                self._serialize_references(response.sources),
            )
            self.sessions.update_activity(chat_session, title=title)
            self.db.commit()
            return user_message, assistant_message
        except Exception:
            self.db.rollback()
            raise

    def get_messages(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> list[ChatMessage]:
        chat_session = self.get_session(knowledge_base_id, session_id)
        return self.sessions.list_messages(chat_session.id)

    def delete_session(
        self,
        knowledge_base_id: str,
        session_id: str,
    ) -> ChatSession:
        chat_session = self.get_session(knowledge_base_id, session_id)
        try:
            self.sessions.delete_messages(chat_session.id)
            self.sessions.delete_session(chat_session)
            self.db.commit()
            return chat_session
        except Exception:
            self.db.rollback()
            raise

    def _get_knowledge_base(self, knowledge_base_id: str):
        knowledge_base = self.knowledge_bases.get_by_id(knowledge_base_id)
        if knowledge_base is None:
            raise ResourceNotFoundException("知识库不存在")
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

    @staticmethod
    def _serialize_references(
        references: Sequence[SourceReference] | None,
    ) -> list[dict[str, object]]:
        return [
            reference.model_dump(mode="json")
            for reference in (references or ())
        ]

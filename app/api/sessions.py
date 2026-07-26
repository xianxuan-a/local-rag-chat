"""Chat-session API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.session import MessageResponse, SessionCreate, SessionResponse
from app.services.chat_history_service import ChatHistoryService


router = APIRouter(prefix="/sessions", tags=["sessions"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ApiResponse[SessionResponse])
def create_session(payload: SessionCreate, db: DatabaseSession):
    """Create one session under an existing knowledge base."""
    session = ChatHistoryService(db).create_session(payload)
    return success_response(
        SessionResponse.model_validate(session),
        status_code=201,
    )


@router.get("", response_model=ApiResponse[list[SessionResponse]])
def list_sessions(knowledge_base_id: UUID, db: DatabaseSession):
    """List only sessions owned by the requested knowledge base."""
    sessions = ChatHistoryService(db).list_sessions(str(knowledge_base_id))
    data = [SessionResponse.model_validate(item) for item in sessions]
    return success_response(data)


@router.get(
    "/{session_id}/messages",
    response_model=ApiResponse[list[MessageResponse]],
)
def list_messages(
    session_id: UUID,
    knowledge_base_id: UUID,
    db: DatabaseSession,
):
    """Load one owned session's messages in stable chronological order."""
    messages = ChatHistoryService(db).get_messages(
        str(knowledge_base_id),
        str(session_id),
    )
    data = [MessageResponse.model_validate(item) for item in messages]
    return success_response(data)


@router.get("/{session_id}", response_model=ApiResponse[SessionResponse])
def get_session(
    session_id: UUID,
    knowledge_base_id: UUID,
    db: DatabaseSession,
):
    """Get one session after validating its knowledge-base ownership."""
    session = ChatHistoryService(db).get_session(
        str(knowledge_base_id),
        str(session_id),
    )
    return success_response(SessionResponse.model_validate(session))


@router.delete("/{session_id}", response_model=ApiResponse[SessionResponse])
def delete_session(
    session_id: UUID,
    knowledge_base_id: UUID,
    db: DatabaseSession,
):
    """Atomically delete one owned session and all of its messages."""
    session = ChatHistoryService(db).delete_session(
        str(knowledge_base_id),
        str(session_id),
    )
    return success_response(SessionResponse.model_validate(session))

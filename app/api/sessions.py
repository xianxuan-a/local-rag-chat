"""Chat-session API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.session import SessionCreate, SessionResponse
from app.services.chat_history_service import ChatHistoryService


router = APIRouter(prefix="/sessions", tags=["sessions"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ApiResponse[SessionResponse])
def create_session(payload: SessionCreate, db: DatabaseSession):
    """Reserved session-create endpoint."""
    session = ChatHistoryService(db).create_session(payload)
    return success_response(SessionResponse.model_validate(session))


@router.get("", response_model=ApiResponse[list[SessionResponse]])
def list_sessions(knowledge_base_id: UUID, db: DatabaseSession):
    """Reserved session-list endpoint."""
    sessions = ChatHistoryService(db).list_sessions(str(knowledge_base_id))
    data = [SessionResponse.model_validate(item) for item in sessions]
    return success_response(data)


@router.get("/{session_id}", response_model=ApiResponse[SessionResponse])
def get_session(session_id: UUID, db: DatabaseSession):
    """Reserved single-session endpoint."""
    session = ChatHistoryService(db).get_session(str(session_id))
    return success_response(SessionResponse.model_validate(session))


@router.delete("/{session_id}", response_model=ApiResponse[SessionResponse])
def delete_session(session_id: UUID, db: DatabaseSession):
    """Reserved session-delete endpoint."""
    session = ChatHistoryService(db).delete_session(str(session_id))
    return success_response(SessionResponse.model_validate(session))

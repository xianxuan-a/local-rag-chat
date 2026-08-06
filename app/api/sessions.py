"""Owned, bounded chat-session and message-history API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.exceptions import ConflictException
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import UserRole
from app.schemas.session import (
    FeedbackResponse,
    FeedbackUpdate,
    MessageResponse,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
)
from app.services.chat_history_service import ChatHistoryService
from app.services.runtime_coordinator import RuntimeCoordinator, get_runtime_coordinator


router = APIRouter(prefix="/sessions", tags=["sessions"])
DatabaseSession = Annotated[Session, Depends(get_db)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


def _owner_id(user: object) -> str | None:
    return None if user.role == UserRole.ADMIN.value else user.id


@router.post("", response_model=ApiResponse[SessionResponse])
def create_session(
    payload: SessionCreate,
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
):
    with runtime.business_write("create_session"):
        summary = ChatHistoryService(db, _owner_id(user)).create_session(payload)
    return success_response(
        SessionResponse.model_validate(summary),
        status_code=201,
    )


@router.get("", response_model=ApiResponse[list[SessionResponse]])
def list_sessions(
    db: DatabaseSession,
    user: CurrentUser,
    knowledge_base_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    sessions = ChatHistoryService(db, _owner_id(user)).list_sessions(
        str(knowledge_base_id) if knowledge_base_id is not None else None,
        limit=limit,
        offset=offset,
    )
    return success_response(
        [SessionResponse.model_validate(item) for item in sessions]
    )


@router.get(
    "/{session_id}/messages",
    response_model=ApiResponse[list[MessageResponse]],
)
def list_messages(
    session_id: UUID,
    knowledge_base_id: UUID,
    db: DatabaseSession,
    user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    messages = ChatHistoryService(db, _owner_id(user)).get_messages(
        str(knowledge_base_id),
        str(session_id),
        limit=limit,
        offset=offset,
    )
    return success_response(
        [MessageResponse.model_validate(item) for item in messages]
    )


@router.put(
    "/{session_id}/messages/{message_id}/feedback",
    response_model=ApiResponse[FeedbackResponse],
)
def update_feedback(
    session_id: UUID,
    message_id: UUID,
    knowledge_base_id: UUID,
    payload: FeedbackUpdate,
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
):
    with runtime.business_write("update_message_feedback"):
        message = ChatHistoryService(db, _owner_id(user)).update_feedback(
            str(knowledge_base_id),
            str(session_id),
            str(message_id),
            payload.value,
            updated_by_id=user.id,
        )
    feedback = message.feedback
    return success_response(
        FeedbackResponse(
            message_id=UUID(message.id),
            value=None if feedback is None else feedback.value,
            updated_at=None if feedback is None else feedback.updated_at,
        )
    )


@router.get("/{session_id}", response_model=ApiResponse[SessionResponse])
def get_session(
    session_id: UUID,
    knowledge_base_id: UUID,
    db: DatabaseSession,
    user: CurrentUser,
):
    summary = ChatHistoryService(db, _owner_id(user)).get_session_summary(
        str(knowledge_base_id),
        str(session_id),
    )
    return success_response(SessionResponse.model_validate(summary))


@router.patch("/{session_id}", response_model=ApiResponse[SessionResponse])
def update_session(
    session_id: UUID,
    knowledge_base_id: UUID,
    payload: SessionUpdate,
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
):
    if runtime.is_chat_active(str(session_id)):
        raise ConflictException("会话正在生成回答，暂时不能修改标题")
    with runtime.business_write("update_session"):
        summary = ChatHistoryService(db, _owner_id(user)).update_session_title(
            str(knowledge_base_id),
            str(session_id),
            payload.title,
        )
    return success_response(SessionResponse.model_validate(summary))


@router.delete("/{session_id}", response_model=ApiResponse[SessionResponse])
def delete_session(
    session_id: UUID,
    knowledge_base_id: UUID,
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
):
    if runtime.is_chat_active(str(session_id)):
        raise ConflictException("会话正在生成回答，暂时不能删除")
    with runtime.business_write("delete_session"):
        summary = ChatHistoryService(db, _owner_id(user)).delete_session(
            str(knowledge_base_id),
            str(session_id),
        )
    return success_response(SessionResponse.model_validate(summary))

"""Persistent synchronous and true NDJSON RAG chat routes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
import time
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.api.dependencies import BusinessWritePermit, CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, ConflictException
from app.core.logger import get_logger
from app.core.observability import RAG_DURATION
from app.core.retrieval_modes import RetrievalMode
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import MessageStatus, UserRole
from app.schemas.chat import (
    CancelChatRequest,
    CancelChatResponse,
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    RetryChatRequest,
)
from app.services.chat_history_service import (
    ChatHistoryService,
    ChatTurn,
    RetryTurn,
)
from app.services.rag_service import RagService
from app.services.retrieval_service import RetrievalService
from app.services.retrieval_orchestrator import RetrievalOrchestrator
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


def _owner_id(user: object) -> str | None:
    return None if user.role == UserRole.ADMIN.value else user.id


@router.post("", response_model=ApiResponse[ChatResponse])
def chat(
    payload: ChatRequest,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
):
    """Run one grounded answer while preserving every turn outcome."""

    _ = settings
    history = ChatHistoryService(db, _owner_id(user))
    effective_settings = runtime.effective_settings()
    requested_mode = (
        payload.mode or effective_settings.DEFAULT_RETRIEVAL_MODE
    )
    turn, active_session_id = _start_turn(
        history,
        runtime,
        payload,
        requested_mode=requested_mode,
    )
    started = time.perf_counter()
    try:
        rag_service = _build_rag_service(
            db,
            effective_settings,
            runtime,
            user_role=user.role,
        )
        bundle = rag_service.prepare_retrieval(payload)
        if bundle is not None:
            history.record_retrieval_audit(
                str(payload.knowledge_base_id),
                turn.session.id,
                turn.assistant_message.id,
                bundle.audit,
            )
        response = rag_service.ask(payload)
        assistant = history.complete_turn(
            str(payload.knowledge_base_id),
            turn,
            response,
        )
        return success_response(
            response.model_copy(
                update={
                    "session_id": UUID(turn.session.id),
                    "user_message_id": UUID(turn.user_message.id),
                    "assistant_message_id": UUID(assistant.id),
                }
            )
        )
    except AppException as exc:
        code = _error_code(exc)
        history.fail_turn(
            str(payload.knowledge_base_id),
            turn,
            partial_content="",
            error_code=code,
            error_message=exc.message,
        )
        raise
    except Exception:
        history.fail_turn(
            str(payload.knowledge_base_id),
            turn,
            partial_content="",
            error_code="CHAT_INTERNAL_ERROR",
            error_message="聊天处理失败",
        )
        raise
    finally:
        runtime.end_chat(active_session_id)
        RAG_DURATION.labels("sync").observe(
            max(0.0, time.perf_counter() - started)
        )


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/x-ndjson": {"schema": {"type": "string"}}
            },
            "description": "Structured streaming chat events",
        }
    },
)
def stream_chat(
    payload: ChatRequest,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
) -> StreamingResponse:
    """Stream real provider deltas and persist completed or partial state."""

    _ = settings
    history = ChatHistoryService(db, _owner_id(user))
    effective_settings = runtime.effective_settings()
    turn, active_session_id = _start_turn(
        history,
        runtime,
        payload,
        requested_mode=(
            payload.mode or effective_settings.DEFAULT_RETRIEVAL_MODE
        ),
    )
    runtime.bind_chat_message(active_session_id, turn.assistant_message.id)
    rag_service = _build_rag_service(
        db,
        effective_settings,
        runtime,
        user_role=user.role,
    )
    return _turn_stream_response(
        payload=payload,
        history=history,
        runtime=runtime,
        rag_service=rag_service,
        turn=turn,
        active_session_id=active_session_id,
    )


@router.post(
    "/messages/{assistant_message_id}/retry/stream",
    response_class=StreamingResponse,
)
def retry_stream_chat(
    assistant_message_id: UUID,
    payload: RetryChatRequest,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
) -> StreamingResponse:
    """Regenerate one assistant message without duplicating its user question."""

    _ = settings
    session_id = str(payload.session_id)
    runtime.begin_chat(session_id)
    history = ChatHistoryService(db, _owner_id(user))
    try:
        retry = history.prepare_retry(
            str(payload.knowledge_base_id),
            session_id,
            str(assistant_message_id),
            requested_mode=(
                payload.mode
                or runtime.effective_settings().DEFAULT_RETRIEVAL_MODE
            ),
        )
        runtime.bind_chat_message(session_id, retry.assistant_message.id)
    except Exception:
        runtime.end_chat(session_id)
        raise
    chat_request = ChatRequest(
        knowledge_base_id=payload.knowledge_base_id,
        session_id=payload.session_id,
        question=retry.user_message.content,
        top_k=payload.top_k,
        mode=payload.mode,
    )
    effective_settings = runtime.effective_settings()
    rag_service = _build_rag_service(
        db,
        effective_settings,
        runtime,
        user_role=user.role,
    )
    return _retry_stream_response(
        payload=chat_request,
        history=history,
        runtime=runtime,
        rag_service=rag_service,
        retry=retry,
        active_session_id=session_id,
    )


@router.post(
    "/messages/{assistant_message_id}/cancel",
    response_model=ApiResponse[CancelChatResponse],
)
def cancel_stream_chat(
    assistant_message_id: UUID,
    payload: CancelChatRequest,
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
    _write_permit: BusinessWritePermit,
):
    """Signal cooperative cancellation for one exact active streamed answer."""

    history = ChatHistoryService(db, _owner_id(user))
    assistant = history.validate_cancel_target(
        str(payload.knowledge_base_id),
        str(payload.session_id),
        str(assistant_message_id),
    )
    if assistant.status == MessageStatus.CANCELLED:
        requested = False
    else:
        requested = runtime.request_chat_cancel(
            str(payload.session_id),
            str(assistant_message_id),
        )
        if not requested:
            raise ConflictException(
                "该回答的生成进程已结束或不在当前服务进程中，请刷新历史状态"
            )
    return success_response(
        CancelChatResponse(
            session_id=payload.session_id,
            assistant_message_id=assistant_message_id,
            cancel_requested=requested,
        )
    )


def _start_turn(
    history: ChatHistoryService,
    runtime: RuntimeCoordinator,
    payload: ChatRequest,
    *,
    requested_mode: RetrievalMode,
) -> tuple[ChatTurn, str]:
    requested_session_id = (
        str(payload.session_id) if payload.session_id is not None else None
    )
    acquired = False
    if requested_session_id is not None:
        runtime.begin_chat(requested_session_id)
        acquired = True
    try:
        turn = history.start_turn(
            str(payload.knowledge_base_id),
            requested_session_id,
            payload.question,
            requested_mode=requested_mode,
        )
        if not acquired:
            runtime.begin_chat(turn.session.id)
        return turn, turn.session.id
    except Exception:
        if acquired and requested_session_id is not None:
            runtime.end_chat(requested_session_id)
        raise


def _turn_stream_response(
    *,
    payload: ChatRequest,
    history: ChatHistoryService,
    runtime: RuntimeCoordinator,
    rag_service: RagService,
    turn: ChatTurn,
    active_session_id: str,
) -> StreamingResponse:
    async def event_stream() -> AsyncGenerator[str, None]:
        started = time.perf_counter()
        partial: list[str] = []
        rag_stream = None
        yield _encode_event(
            ChatStreamEvent(
                type="start",
                session_id=UUID(turn.session.id),
                user_message_id=UUID(turn.user_message.id),
                assistant_message_id=UUID(turn.assistant_message.id),
                retry=False,
                requested_mode=(
                    payload.mode
                    or rag_service.settings.DEFAULT_RETRIEVAL_MODE
                ),
            )
        )
        try:
            bundle = await anyio.to_thread.run_sync(
                lambda: rag_service.prepare_retrieval(
                    payload,
                    cancel_check=lambda: runtime.is_chat_cancel_requested(
                        active_session_id,
                        turn.assistant_message.id,
                    ),
                )
            )
            if runtime.is_chat_cancel_requested(
                active_session_id,
                turn.assistant_message.id,
            ):
                history.cancel_turn(
                    str(payload.knowledge_base_id),
                    turn,
                    partial_content="",
                )
                return
            if bundle is not None:
                history.record_retrieval_audit(
                    str(payload.knowledge_base_id),
                    turn.session.id,
                    turn.assistant_message.id,
                    bundle.audit,
                )
                yield _encode_event(
                    ChatStreamEvent(
                        type="retrieval",
                        session_id=UUID(turn.session.id),
                        assistant_message_id=UUID(
                            turn.assistant_message.id
                        ),
                        **bundle.audit.model_dump(),
                    )
                )
            rag_stream = rag_service.stream(payload)
            while True:
                if runtime.is_chat_cancel_requested(
                    active_session_id,
                    turn.assistant_message.id,
                ):
                    history.cancel_turn(
                        str(payload.knowledge_base_id),
                        turn,
                        partial_content="".join(partial),
                    )
                    return
                completed, value = await anyio.to_thread.run_sync(
                    _next_stream_value,
                    rag_stream,
                )
                cancel_requested = runtime.is_chat_cancel_requested(
                    active_session_id,
                    turn.assistant_message.id,
                )
                if completed:
                    if cancel_requested:
                        history.cancel_turn(
                            str(payload.knowledge_base_id),
                            turn,
                            partial_content="".join(partial),
                        )
                        return
                    response = value
                    break
                delta = value
                partial.append(delta)
                if cancel_requested:
                    history.cancel_turn(
                        str(payload.knowledge_base_id),
                        turn,
                        partial_content="".join(partial),
                    )
                    return
                yield _encode_event(
                    ChatStreamEvent(
                        type="delta",
                        assistant_message_id=UUID(turn.assistant_message.id),
                        content=delta,
                    )
                )
            assistant = history.complete_turn(
                str(payload.knowledge_base_id),
                turn,
                response,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="sources",
                    assistant_message_id=UUID(assistant.id),
                    sources=response.sources,
                    **response_audit(response),
                )
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="done",
                    session_id=UUID(turn.session.id),
                    user_message_id=UUID(turn.user_message.id),
                    assistant_message_id=UUID(assistant.id),
                    **response_audit(response),
                )
            )
        except (asyncio.CancelledError, GeneratorExit):
            history.cancel_turn(
                str(payload.knowledge_base_id),
                turn,
                partial_content="".join(partial),
            )
            logger.info(
                "流式聊天客户端已断开（kb_id=%s, session_id=%s）",
                payload.knowledge_base_id,
                turn.session.id,
            )
            raise
        except AppException as exc:
            error_code = _error_code(exc)
            history.fail_turn(
                str(payload.knowledge_base_id),
                turn,
                partial_content="".join(partial),
                error_code=error_code,
                error_message=exc.message,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="error",
                    session_id=UUID(turn.session.id),
                    assistant_message_id=UUID(turn.assistant_message.id),
                    message=exc.message,
                    code=exc.status_code,
                    error_code=error_code,
                )
            )
        except Exception:
            logger.exception(
                "流式聊天发生未处理错误（kb_id=%s, session_id=%s）",
                payload.knowledge_base_id,
                turn.session.id,
            )
            history.fail_turn(
                str(payload.knowledge_base_id),
                turn,
                partial_content="".join(partial),
                error_code="CHAT_INTERNAL_ERROR",
                error_message="流式聊天处理失败",
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="error",
                    session_id=UUID(turn.session.id),
                    assistant_message_id=UUID(turn.assistant_message.id),
                    message="流式聊天处理失败",
                    code=500,
                    error_code="CHAT_INTERNAL_ERROR",
                )
            )
        finally:
            if rag_stream is not None:
                rag_stream.close()
            runtime.end_chat(active_session_id)
            RAG_DURATION.labels("stream").observe(
                max(0.0, time.perf_counter() - started)
            )

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_rag_service(
    db: Session,
    settings: Settings,
    runtime: RuntimeCoordinator,
    *,
    user_role: str,
) -> RagService:
    retrieval = RetrievalService(db, settings, runtime)
    orchestrator = RetrievalOrchestrator(
        retrieval,
        runtime.web_search,
        settings,
    )
    return RagService(
        retrieval,
        settings,
        retrieval_orchestrator=orchestrator,
        user_role=user_role,
    )


def response_audit(response: ChatResponse) -> dict[str, object]:
    return {
        "requested_mode": response.requested_mode,
        "effective_mode": response.effective_mode,
        "web_search_triggered": response.web_search_triggered,
        "web_search_status": response.web_search_status,
        "web_trigger_reason": response.web_trigger_reason,
        "knowledge_source_count": response.knowledge_source_count,
        "web_source_count": response.web_source_count,
        "fallback_reason": response.fallback_reason,
    }


def _retry_stream_response(
    *,
    payload: ChatRequest,
    history: ChatHistoryService,
    runtime: RuntimeCoordinator,
    rag_service: RagService,
    retry: RetryTurn,
    active_session_id: str,
) -> StreamingResponse:
    async def event_stream() -> AsyncGenerator[str, None]:
        started = time.perf_counter()
        rag_stream = None
        yield _encode_event(
            ChatStreamEvent(
                type="start",
                session_id=UUID(retry.session.id),
                user_message_id=UUID(retry.user_message.id),
                assistant_message_id=UUID(retry.assistant_message.id),
                retry=True,
                requested_mode=(
                    payload.mode
                    or rag_service.settings.DEFAULT_RETRIEVAL_MODE
                ),
            )
        )
        try:
            bundle = await anyio.to_thread.run_sync(
                lambda: rag_service.prepare_retrieval(
                    payload,
                    cancel_check=lambda: runtime.is_chat_cancel_requested(
                        active_session_id,
                        retry.assistant_message.id,
                    ),
                )
            )
            if runtime.is_chat_cancel_requested(
                active_session_id,
                retry.assistant_message.id,
            ):
                history.fail_retry(
                    str(payload.knowledge_base_id),
                    retry,
                    error_code="CLIENT_CANCELLED",
                    error_message="用户已停止本次重试",
                )
                return
            if bundle is not None:
                history.record_retrieval_audit(
                    str(payload.knowledge_base_id),
                    retry.session.id,
                    retry.assistant_message.id,
                    bundle.audit,
                )
                yield _encode_event(
                    ChatStreamEvent(
                        type="retrieval",
                        session_id=UUID(retry.session.id),
                        assistant_message_id=UUID(
                            retry.assistant_message.id
                        ),
                        retry=True,
                        **bundle.audit.model_dump(),
                    )
                )
            rag_stream = rag_service.stream(payload)
            while True:
                if runtime.is_chat_cancel_requested(
                    active_session_id,
                    retry.assistant_message.id,
                ):
                    history.fail_retry(
                        str(payload.knowledge_base_id),
                        retry,
                        error_code="CLIENT_CANCELLED",
                        error_message="用户已停止本次重试",
                    )
                    return
                completed, value = await anyio.to_thread.run_sync(
                    _next_stream_value,
                    rag_stream,
                )
                cancel_requested = runtime.is_chat_cancel_requested(
                    active_session_id,
                    retry.assistant_message.id,
                )
                if completed:
                    if cancel_requested:
                        history.fail_retry(
                            str(payload.knowledge_base_id),
                            retry,
                            error_code="CLIENT_CANCELLED",
                            error_message="用户已停止本次重试",
                        )
                        return
                    response = value
                    break
                delta = value
                if cancel_requested:
                    history.fail_retry(
                        str(payload.knowledge_base_id),
                        retry,
                        error_code="CLIENT_CANCELLED",
                        error_message="用户已停止本次重试",
                    )
                    return
                yield _encode_event(
                    ChatStreamEvent(
                        type="delta",
                        assistant_message_id=UUID(retry.assistant_message.id),
                        content=delta,
                    )
                )
            assistant = history.complete_retry(
                str(payload.knowledge_base_id),
                retry,
                response,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="sources",
                    assistant_message_id=UUID(assistant.id),
                    sources=response.sources,
                    **response_audit(response),
                )
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="done",
                    session_id=UUID(retry.session.id),
                    user_message_id=UUID(retry.user_message.id),
                    assistant_message_id=UUID(assistant.id),
                    retry=True,
                    **response_audit(response),
                )
            )
        except (asyncio.CancelledError, GeneratorExit):
            logger.info(
                "流式重试客户端已断开（session_id=%s, message_id=%s）",
                retry.session.id,
                retry.assistant_message.id,
            )
            raise
        except AppException as exc:
            error_code = _error_code(exc)
            history.fail_retry(
                str(payload.knowledge_base_id),
                retry,
                error_code=error_code,
                error_message=exc.message,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="error",
                    session_id=UUID(retry.session.id),
                    assistant_message_id=UUID(retry.assistant_message.id),
                    message=exc.message,
                    code=exc.status_code,
                    error_code=error_code,
                    retry=True,
                )
            )
        except Exception:
            logger.exception(
                "流式重试发生未处理错误（session_id=%s, message_id=%s）",
                retry.session.id,
                retry.assistant_message.id,
            )
            history.fail_retry(
                str(payload.knowledge_base_id),
                retry,
                error_code="CHAT_INTERNAL_ERROR",
                error_message="流式重试处理失败",
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="error",
                    session_id=UUID(retry.session.id),
                    assistant_message_id=UUID(retry.assistant_message.id),
                    message="流式重试处理失败",
                    code=500,
                    error_code="CHAT_INTERNAL_ERROR",
                    retry=True,
                )
            )
        finally:
            if rag_stream is not None:
                rag_stream.close()
            runtime.end_chat(active_session_id)
            RAG_DURATION.labels("stream_retry").observe(
                max(0.0, time.perf_counter() - started)
            )

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _error_code(exc: AppException) -> str:
    if isinstance(exc.data, dict):
        explicit = exc.data.get("error_code")
        if isinstance(explicit, str) and explicit:
            return explicit
    message = exc.message.lower()
    if exc.status_code == 504:
        return "MODEL_TIMEOUT"
    if "活动索引" in exc.message or "collection" in message:
        return "NO_ACTIVE_INDEX"
    if exc.status_code == 503:
        return "MODEL_UNAVAILABLE"
    if exc.status_code == 409:
        return "CHAT_CONFLICT"
    if exc.status_code == 404:
        return "CHAT_RESOURCE_NOT_FOUND"
    if exc.status_code == 422:
        return "CHAT_VALIDATION_ERROR"
    return "CHAT_REQUEST_FAILED"


def _next_stream_value(
    stream: Generator[str, None, ChatResponse],
) -> tuple[bool, str | ChatResponse]:
    """Advance a sync RAG iterator without leaking StopIteration into a Future."""

    try:
        return False, next(stream)
    except StopIteration as completed:
        return True, completed.value


def _encode_event(event: ChatStreamEvent) -> str:
    return event.model_dump_json(exclude_none=True) + "\n"

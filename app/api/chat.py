"""RAG chat API route."""

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.core.logger import get_logger
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.chat import ChatRequest, ChatResponse, ChatStreamEvent
from app.services.chat_history_service import ChatHistoryService
from app.services.rag_service import RagService
from app.services.retrieval_service import RetrievalService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


@router.post("", response_model=ApiResponse[ChatResponse])
def chat(
    payload: ChatRequest,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    """Synchronously retrieve full chunks and generate one grounded answer."""

    history = ChatHistoryService(db)
    chat_session = history.prepare_session_for_chat(
        str(payload.knowledge_base_id),
        str(payload.session_id) if payload.session_id is not None else None,
        payload.question,
    )
    retrieval = RetrievalService(db, settings, runtime)
    response = RagService(retrieval, settings).ask(payload)
    history.save_exchange(
        str(payload.knowledge_base_id),
        chat_session.id,
        payload.question.strip(),
        response,
    )
    response = response.model_copy(
        update={"session_id": UUID(chat_session.id)}
    )
    return success_response(response)


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/x-ndjson": {
                    "schema": {"type": "string"},
                }
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
) -> StreamingResponse:
    """Stream genuine model deltas as structured UTF-8 NDJSON events."""

    history = ChatHistoryService(db)
    chat_session = history.prepare_session_for_chat(
        str(payload.knowledge_base_id),
        str(payload.session_id) if payload.session_id is not None else None,
        payload.question,
    )
    rag_service = RagService(
        RetrievalService(db, settings, runtime),
        settings,
    )

    def event_stream() -> Generator[str, None, None]:
        yield _encode_event(
            ChatStreamEvent(
                type="start",
                session_id=UUID(chat_session.id),
            )
        )
        try:
            rag_stream = rag_service.stream(payload)
            try:
                while True:
                    try:
                        delta = next(rag_stream)
                    except StopIteration as completed:
                        response = completed.value
                        break
                    yield _encode_event(
                        ChatStreamEvent(
                            type="delta",
                            content=delta,
                        )
                    )
            finally:
                rag_stream.close()
            _, assistant_message = history.save_exchange(
                str(payload.knowledge_base_id),
                chat_session.id,
                payload.question.strip(),
                response,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="sources",
                    sources=response.sources,
                )
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="done",
                    session_id=UUID(chat_session.id),
                    message_id=UUID(assistant_message.id),
                )
            )
        except GeneratorExit:
            db.rollback()
            logger.info(
                "流式聊天客户端已断开（kb_id=%s, session_id=%s）",
                payload.knowledge_base_id,
                chat_session.id,
            )
            raise
        except AppException as exc:
            db.rollback()
            logger.warning(
                "流式聊天失败（kb_id=%s, session_id=%s, code=%s）",
                payload.knowledge_base_id,
                chat_session.id,
                exc.code,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="error",
                    message=exc.message,
                    code=exc.code,
                )
            )
        except Exception:
            db.rollback()
            logger.exception(
                "流式聊天发生未处理错误（kb_id=%s, session_id=%s）",
                payload.knowledge_base_id,
                chat_session.id,
            )
            yield _encode_event(
                ChatStreamEvent(
                    type="error",
                    message="流式聊天处理失败",
                    code=500,
                )
            )

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _encode_event(event: ChatStreamEvent) -> str:
    return event.model_dump_json(exclude_none=True) + "\n"

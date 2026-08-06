"""Direct, authenticated inspection of the real retrieval pipeline."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import ModelServiceException
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import UserRole
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievalResult
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.retrieval_service import RetrievalService
from app.services.runtime_coordinator import RuntimeCoordinator, get_runtime_coordinator


router = APIRouter(prefix="/retrieval", tags=["retrieval"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


@router.post("", response_model=ApiResponse[RetrievalResponse])
def execute_retrieval(
    payload: RetrievalRequest,
    db: DatabaseSession,
    _settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    KnowledgeBaseService(db).get_knowledge_base(
        str(payload.knowledge_base_id),
        None if user.role == UserRole.ADMIN.value else user.id,
    )
    started = time.perf_counter()
    try:
        chunks = RetrievalService(
            db, runtime.effective_settings(), runtime
        ).retrieve_chunks(
            str(payload.knowledge_base_id),
            payload.query,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            require_active_index=True,
            apply_default_threshold=False,
        )
    except ModelServiceException as exc:
        status_code = 504 if "超时" in exc.message else 503
        raise ModelServiceException(
            exc.message, status_code=status_code, data=exc.data
        ) from exc
    elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
    results = [
        RetrievalResult(
            rank=index,
            score=chunk.score,
            file_id=chunk.file_id,
            file_name=chunk.file_name,
            chunk_id=chunk.chunk_id,
            content=chunk.content,
            metadata=chunk.metadata,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    return success_response(
        RetrievalResponse(
            result_count=len(results),
            query_time_ms=elapsed_ms,
            results=results,
        )
    )

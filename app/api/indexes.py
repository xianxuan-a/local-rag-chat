"""Read-only index lifecycle state endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.index import IndexStateResponse
from app.services.index_state_service import IndexStateService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/indexes", tags=["indexes"])
DatabaseSession = Annotated[Session, Depends(get_db)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


@router.get("", response_model=ApiResponse[list[IndexStateResponse]])
def list_indexes(
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
    knowledge_base_id: Annotated[UUID | None, Query()] = None,
):
    states = IndexStateService(db, runtime).list_states(
        user=user,
        knowledge_base_id=(
            str(knowledge_base_id) if knowledge_base_id is not None else None
        ),
    )
    return success_response(states)

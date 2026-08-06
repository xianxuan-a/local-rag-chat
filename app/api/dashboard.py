"""Authenticated Dashboard aggregate endpoint."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DatabaseSession = Annotated[Session, Depends(get_db)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


@router.get("", response_model=ApiResponse[DashboardResponse])
def get_dashboard(
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
    knowledge_base_id: Annotated[UUID | None, Query()] = None,
    window_days: Annotated[int, Query(ge=1, le=30)] = 7,
    recent_limit: Annotated[int, Query(ge=1, le=20)] = 5,
):
    snapshot = DashboardService(db, runtime).get_snapshot(
        user=user,
        knowledge_base_id=(
            str(knowledge_base_id)
            if knowledge_base_id is not None
            else None
        ),
        window_days=window_days,
        recent_limit=recent_limit,
    )
    return success_response(snapshot)

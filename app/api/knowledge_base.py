"""Knowledge-base API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseResponse
from app.schemas.rebuild import (
    CollectionMaintenanceResponse,
    RebuildResponse,
)
from app.services.knowledge_base_rebuild_service import (
    KnowledgeBaseRebuildService,
)
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


@router.post(
    "",
    response_model=ApiResponse[KnowledgeBaseResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_base(payload: KnowledgeBaseCreate, db: DatabaseSession):
    """Create a knowledge base."""
    knowledge_base = KnowledgeBaseService(db).create_knowledge_base(payload)
    return success_response(
        KnowledgeBaseResponse.model_validate(knowledge_base),
        status_code=status.HTTP_201_CREATED,
    )


@router.get("", response_model=ApiResponse[list[KnowledgeBaseResponse]])
def list_knowledge_bases(db: DatabaseSession):
    """List all knowledge bases."""
    knowledge_bases = KnowledgeBaseService(db).list_knowledge_bases()
    data = [KnowledgeBaseResponse.model_validate(item) for item in knowledge_bases]
    return success_response(data)


@router.get(
    "/{knowledge_base_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
)
def get_knowledge_base(knowledge_base_id: UUID, db: DatabaseSession):
    """Return one knowledge base."""
    knowledge_base = KnowledgeBaseService(db).get_knowledge_base(
        str(knowledge_base_id)
    )
    return success_response(KnowledgeBaseResponse.model_validate(knowledge_base))


@router.post(
    "/{knowledge_base_id}/rebuild",
    response_model=ApiResponse[RebuildResponse],
)
def rebuild_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    result = KnowledgeBaseRebuildService(
        db, settings, runtime
    ).rebuild(str(knowledge_base_id))
    return success_response(result)


@router.post(
    "/{knowledge_base_id}/rollback",
    response_model=ApiResponse[CollectionMaintenanceResponse],
)
def rollback_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    result = KnowledgeBaseRebuildService(
        db, settings, runtime
    ).rollback(str(knowledge_base_id))
    return success_response(result)


@router.post(
    "/{knowledge_base_id}/abort-building",
    response_model=ApiResponse[CollectionMaintenanceResponse],
)
def abort_building_collection(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    result = KnowledgeBaseRebuildService(
        db, settings, runtime
    ).abort_building(str(knowledge_base_id))
    return success_response(result)


@router.post(
    "/{knowledge_base_id}/cleanup-retired",
    response_model=ApiResponse[CollectionMaintenanceResponse],
)
def cleanup_retired_collection(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    result = KnowledgeBaseRebuildService(
        db, settings, runtime
    ).cleanup_retired(str(knowledge_base_id))
    return success_response(result)


@router.delete(
    "/{knowledge_base_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
)
def delete_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
):
    """Delete an empty knowledge base."""
    knowledge_base = KnowledgeBaseService(
        db, settings, runtime
    ).delete_knowledge_base(
        str(knowledge_base_id)
    )
    return success_response(KnowledgeBaseResponse.model_validate(knowledge_base))

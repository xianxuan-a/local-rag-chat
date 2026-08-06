"""Knowledge-base API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import AdminUser, CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationException
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.schemas.job import JobResponse
from app.schemas.index import CleanupIndexesRequest
from app.schemas.rebuild import (
    CollectionMaintenanceResponse,
)
from app.services.knowledge_base_rebuild_service import (
    KnowledgeBaseRebuildService,
)
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.job_service import JobService
from app.models import JobType, UserRole
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
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    """Create a knowledge base."""
    with runtime.business_write("create_knowledge_base"):
        knowledge_base = KnowledgeBaseService(db).create_knowledge_base(
            payload, user.id
        )
    return success_response(
        KnowledgeBaseResponse.from_record(
            knowledge_base,
            embedding_model=settings.EMBEDDING_MODEL,
        ),
        status_code=status.HTTP_201_CREATED,
    )


@router.get("", response_model=ApiResponse[list[KnowledgeBaseResponse]])
def list_knowledge_bases(
    db: DatabaseSession, settings: AppSettings, user: CurrentUser
):
    """List all knowledge bases."""
    owner_id = None if user.role == UserRole.ADMIN.value else user.id
    knowledge_bases = KnowledgeBaseService(db).list_knowledge_bases(owner_id)
    data = [
        KnowledgeBaseResponse.from_record(
            item,
            embedding_model=settings.EMBEDDING_MODEL,
        )
        for item in knowledge_bases
    ]
    return success_response(data)


@router.get(
    "/{knowledge_base_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
)
def get_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    user: CurrentUser,
):
    """Return one knowledge base."""
    knowledge_base = KnowledgeBaseService(db).get_knowledge_base(
        str(knowledge_base_id),
        None if user.role == UserRole.ADMIN.value else user.id,
    )
    return success_response(
        KnowledgeBaseResponse.from_record(
            knowledge_base,
            embedding_model=settings.EMBEDDING_MODEL,
        )
    )


@router.patch(
    "/{knowledge_base_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
)
def update_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeBaseUpdate,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    if not payload.model_fields_set:
        raise ValidationException("至少需要提供一个可更新字段", status_code=422)
    if "name" in payload.model_fields_set and payload.name is None:
        raise ValidationException("知识库名称不能为空", status_code=422)
    with runtime.business_write("update_knowledge_base"):
        knowledge_base = KnowledgeBaseService(db).update_knowledge_base(
            str(knowledge_base_id),
            payload,
            None if user.role == UserRole.ADMIN.value else user.id,
        )
    return success_response(
        KnowledgeBaseResponse.from_record(
            knowledge_base,
            embedding_model=settings.EMBEDDING_MODEL,
        )
    )


@router.post(
    "/{knowledge_base_id}/rebuild",
    response_model=ApiResponse[JobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def rebuild_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: AdminUser,
):
    _ = settings
    knowledge_base = KnowledgeBaseService(db).get_knowledge_base(
        str(knowledge_base_id),
        None,
    )
    with runtime.admin_operation("submit_kb_rebuild"):
        job = JobService(db).submit(
            job_type=JobType.KB_REBUILD,
            created_by_id=user.id,
            resource_type="KNOWLEDGE_BASE",
            resource_id=knowledge_base.id,
            resource_name_snapshot=knowledge_base.name,
            max_attempts=2,
        )
    return success_response(
        JobResponse.model_validate(job),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/{knowledge_base_id}/rollback",
    response_model=ApiResponse[CollectionMaintenanceResponse],
)
def rollback_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: AdminUser,
):
    KnowledgeBaseService(db).get_knowledge_base(
        str(knowledge_base_id),
        None,
    )
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
    user: AdminUser,
):
    KnowledgeBaseService(db).get_knowledge_base(
        str(knowledge_base_id),
        None,
    )
    result = KnowledgeBaseRebuildService(
        db, settings, runtime
    ).abort_building(str(knowledge_base_id))
    return success_response(result)


@router.post(
    "/{knowledge_base_id}/cleanup-retired",
    response_model=ApiResponse[JobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def cleanup_retired_collection(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: AdminUser,
    payload: Annotated[
        CleanupIndexesRequest,
        Body(),
    ] = CleanupIndexesRequest(),
):
    knowledge_base = KnowledgeBaseService(db).get_knowledge_base(
        str(knowledge_base_id),
        None,
    )
    with runtime.admin_operation("submit_cleanup_retired"):
        job = JobService(db).submit(
            job_type=JobType.KB_CLEANUP_RETIRED,
            created_by_id=user.id,
            resource_type="KNOWLEDGE_BASE",
            resource_id=knowledge_base.id,
            resource_name_snapshot=knowledge_base.name,
            collection_name=knowledge_base.cleanup_collection_name,
            payload={
                "cleanup_previous": payload.cleanup_previous,
                "cleanup_orphans": payload.cleanup_orphans,
            },
            max_attempts=2,
        )
    return success_response(
        JobResponse.model_validate(job),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.delete(
    "/{knowledge_base_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
)
def delete_knowledge_base(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    """Delete an empty knowledge base."""
    knowledge_base = KnowledgeBaseService(
        db, settings, runtime
    ).delete_knowledge_base(
        str(knowledge_base_id),
        None if user.role == UserRole.ADMIN.value else user.id,
    )
    return success_response(
        KnowledgeBaseResponse.from_record(
            knowledge_base,
            embedding_model=settings.EMBEDDING_MODEL,
        )
    )

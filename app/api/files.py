"""File API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictException, ResourceNotFoundException
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.file import FileRecordPage, FileRecordResponse, FileUploadResponse
from app.schemas.job import JobResponse
from app.models import FileRecord, Job, JobType, KnowledgeBase, UserRole
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService
from app.services.file_service import FileService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/files", tags=["files"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


def _owned_knowledge_base(
    db: Session, knowledge_base_id: str, user: object
) -> KnowledgeBase:
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or (
        user.role != UserRole.ADMIN.value
        and knowledge_base.owner_id != user.id
    ):
        raise ResourceNotFoundException("知识库不存在")
    return knowledge_base


def _owned_file(db: Session, file_id: str, user: object) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if record is None:
        raise ResourceNotFoundException("文件不存在")
    _owned_knowledge_base(db, record.knowledge_base_id, user)
    return record


def _file_response(
    db: Session,
    settings: Settings,
    record: FileRecord,
) -> FileRecordResponse:
    knowledge_base = db.get(KnowledgeBase, record.knowledge_base_id)
    if knowledge_base is None:
        raise ResourceNotFoundException("知识库不存在")
    job = (
        db.get(Job, record.processing_job_id)
        if record.processing_job_id is not None
        else None
    )
    return FileRecordResponse.from_record(
        record,
        settings=settings,
        knowledge_base=knowledge_base,
        job=job,
    )


@router.post(
    "/upload",
    response_model=ApiResponse[FileUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    knowledge_base_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    """Persist one validated upload and its PENDING database record."""
    _owned_knowledge_base(db, str(knowledge_base_id), user)
    with runtime.business_write("upload_file"):
        record = FileService(db, settings, runtime).upload_file(
            str(knowledge_base_id), file
        )
    data = FileUploadResponse.model_validate(
        _file_response(db, settings, record).model_dump()
    )
    return success_response(data, status_code=status.HTTP_201_CREATED)


@router.get("", response_model=ApiResponse[list[FileRecordResponse]])
def list_files(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Deprecated array response retained for one release."""
    knowledge_base = _owned_knowledge_base(db, str(knowledge_base_id), user)
    records, total = FileService(db, settings, runtime).list_files_page(
        str(knowledge_base_id), limit=limit, offset=offset
    )
    data = [
        FileRecordResponse.from_record(
            record,
            settings=settings,
            knowledge_base=knowledge_base,
            job=job,
        )
        for record, job in records
    ]
    response = success_response(data)
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "next-release"
    response.headers["X-Total-Count"] = str(total)
    return response


@router.get("/page", response_model=ApiResponse[FileRecordPage])
def list_files_page(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    knowledge_base = _owned_knowledge_base(db, str(knowledge_base_id), user)
    records, total = FileService(db, settings, runtime).list_files_page(
        str(knowledge_base_id), limit=limit, offset=offset
    )
    items = [
        FileRecordResponse.from_record(
            record,
            settings=settings,
            knowledge_base=knowledge_base,
            job=job,
        )
        for record, job in records
    ]
    return success_response(
        FileRecordPage(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/{file_id}", response_model=ApiResponse[FileRecordResponse])
def get_file(
    file_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    """Return one real file record."""
    _owned_file(db, str(file_id), user)
    record = FileService(db, settings, runtime).get_file(str(file_id))
    return success_response(_file_response(db, settings, record))


@router.post(
    "/{file_id}/process",
    response_model=ApiResponse[JobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def process_file(
    file_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    """Queue parsing, embedding, and indexing and return a durable Job."""
    _ = settings
    record = _owned_file(db, str(file_id), user)
    with runtime.admin_operation("submit_file_process"):
        with runtime.vector_write_lock:
            job = JobService(db).submit(
                job_type=JobType.FILE_PROCESS,
                created_by_id=user.id,
                resource_type="FILE",
                resource_id=record.id,
                resource_name_snapshot=record.original_name,
                max_attempts=2,
            )
    return success_response(
        JobResponse.model_validate(job),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.delete("/{file_id}", response_model=ApiResponse[FileRecordResponse])
def delete_file(
    file_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    """Safely delete one managed file and its database record."""
    record = _owned_file(db, str(file_id), user)
    jobs = JobRepository(db)
    if jobs.has_nonterminal(resource_type="FILE", resource_id=record.id):
        raise ConflictException("文件仍被非终态 Job 引用")
    if jobs.has_nonterminal_knowledge_base_job(
        record.knowledge_base_id
    ):
        raise ConflictException("文件所属知识库仍有非终态维护 Job")
    knowledge_base = db.get(KnowledgeBase, record.knowledge_base_id)
    if (
        knowledge_base is not None
        and knowledge_base.active_collection_name
        and jobs.collection_is_pinned(knowledge_base.active_collection_name)
    ):
        raise ConflictException("文件所属 Collection 正被评估 Job pin")
    record = FileService(db, settings, runtime).delete_file(record.id)
    return success_response(_file_response(db, settings, record))

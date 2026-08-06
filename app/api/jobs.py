"""Job audit, cancellation, and explicit retry routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.core.exceptions import ResourceNotFoundException
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import Job, JobType, UserRole
from app.repositories.job_repository import JobRepository
from app.schemas.job import JobResponse
from app.services.job_service import JobService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/jobs", tags=["jobs"])
DatabaseSession = Annotated[Session, Depends(get_db)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


def _owned_job(db: Session, job_id: str, user: object) -> Job:
    job = db.get(Job, job_id)
    if job is None or (
        user.role != UserRole.ADMIN.value and job.created_by_id != user.id
    ):
        raise ResourceNotFoundException("Job 不存在")
    return job


@router.get("", response_model=ApiResponse[list[JobResponse]])
def list_jobs(db: DatabaseSession, user: CurrentUser):
    jobs = JobRepository(db).list_for_user(
        user.id, is_admin=user.role == UserRole.ADMIN.value
    )
    return success_response([JobResponse.model_validate(job) for job in jobs])


@router.get("/{job_id}", response_model=ApiResponse[JobResponse])
def get_job(job_id: UUID, db: DatabaseSession, user: CurrentUser):
    return success_response(
        JobResponse.model_validate(_owned_job(db, str(job_id), user))
    )


@router.post("/{job_id}/cancel", response_model=ApiResponse[JobResponse])
def cancel_job(job_id: UUID, db: DatabaseSession, user: CurrentUser):
    _owned_job(db, str(job_id), user)
    job = JobService(db).cancel(str(job_id))
    return success_response(JobResponse.model_validate(job))


@router.post("/{job_id}/retry", response_model=ApiResponse[JobResponse])
def retry_job(
    job_id: UUID,
    db: DatabaseSession,
    runtime: RagRuntime,
    user: CurrentUser,
):
    original = _owned_job(db, str(job_id), user)
    job_type = JobType(original.job_type)
    if job_type is JobType.BACKUP:
        if user.role != UserRole.ADMIN.value:
            raise ResourceNotFoundException("Job 不存在")
        with runtime.backup_exclusive():
            job = JobService(db).manual_retry(str(job_id), user.id)
    elif job_type is JobType.RAG_EVALUATION:
        with runtime.business_write("retry_evaluation"):
            with runtime.vector_write_lock:
                job = JobService(db).manual_retry(str(job_id), user.id)
    else:
        with runtime.admin_operation("retry_maintenance_job"):
            if job_type is JobType.FILE_PROCESS:
                with runtime.vector_write_lock:
                    job = JobService(db).manual_retry(
                        str(job_id), user.id
                    )
            else:
                job = JobService(db).manual_retry(str(job_id), user.id)
    return success_response(JobResponse.model_validate(job))

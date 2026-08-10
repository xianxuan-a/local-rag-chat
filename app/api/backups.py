"""Administrator submission endpoint for online logical backups."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import AdminUser
from app.core.config import Settings, get_settings
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.models import JobType
from app.schemas.job import JobResponse
from app.services.job_service import JobService
from app.services.runtime_coordinator import (
    RuntimeCoordinator,
    get_runtime_coordinator,
)


router = APIRouter(prefix="/backups", tags=["backups"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[
    RuntimeCoordinator, Depends(get_runtime_coordinator)
]


@router.post(
    "",
    response_model=ApiResponse[JobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_backup(
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    admin: AdminUser,
):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:10]
    output = (
        settings.BACKUP_DIR / f"online-logical-{stamp}-{suffix}.zip"
    ).resolve()
    partial = output.with_name(f"{output.name}.partial")
    # Enter the writer-preferring exclusive gate at submission time so the
    # draining row and queued Job become visible before any new business write
    # can acquire a shared permit.
    with runtime.backup_exclusive():
        job = JobService(db).submit(
            job_type=JobType.BACKUP,
            created_by_id=admin.id,
            resource_type="SYSTEM",
            resource_name_snapshot="online-logical-backup",
            payload={
                "output_path": str(output),
                "partial_path": str(partial),
            },
            max_attempts=1,
        )
    return success_response(
        JobResponse.model_validate(job),
        status_code=status.HTTP_202_ACCEPTED,
    )

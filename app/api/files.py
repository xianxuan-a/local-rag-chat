"""File API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.file import FileRecordResponse, FileUploadResponse
from app.services.file_service import FileService


router = APIRouter(prefix="/files", tags=["files"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


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
):
    """Persist one validated upload and its PENDING database record."""
    record = FileService(db, settings).upload_file(str(knowledge_base_id), file)
    data = FileUploadResponse.from_record(record)
    return success_response(data, status_code=status.HTTP_201_CREATED)


@router.get("", response_model=ApiResponse[list[FileRecordResponse]])
def list_files(
    knowledge_base_id: UUID,
    db: DatabaseSession,
    settings: AppSettings,
):
    """Reserved file-list endpoint."""
    records = FileService(db, settings).list_files(str(knowledge_base_id))
    data = [FileRecordResponse.model_validate(item) for item in records]
    return success_response(data)


@router.get("/{file_id}", response_model=ApiResponse[FileRecordResponse])
def get_file(file_id: UUID, db: DatabaseSession, settings: AppSettings):
    """Reserved single-file endpoint."""
    record = FileService(db, settings).get_file(str(file_id))
    return success_response(FileRecordResponse.model_validate(record))


@router.delete("/{file_id}", response_model=ApiResponse[FileRecordResponse])
def delete_file(file_id: UUID, db: DatabaseSession, settings: AppSettings):
    """Reserved file-delete endpoint."""
    record = FileService(db, settings).delete_file(str(file_id))
    return success_response(FileRecordResponse.model_validate(record))

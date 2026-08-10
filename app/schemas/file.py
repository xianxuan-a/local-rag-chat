"""Uploaded-file response schemas."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.file_record import FileStatus


class FileRecordResponse(BaseModel):
    """Public metadata for an uploaded file."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    original_name: str
    stored_name: str
    file_path: str
    file_type: str
    file_size: int = Field(ge=0)
    md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: FileStatus
    chunk_count: int = Field(ge=0)
    progress: int = Field(ge=0, le=100)
    has_active_vectors: bool
    active_index_config_hash: str | None
    error_message: str | None
    processing_job_id: UUID | None
    last_successful_indexed_at: datetime | None
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int = Field(ge=1)
    vector_metric: str
    collection_name: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(
        cls,
        record: Any,
        *,
        settings: Any,
        knowledge_base: Any,
        job: Any = None,
    ) -> Self:
        status_value = (
            record.status.value
            if isinstance(record.status, FileStatus)
            else str(record.status)
        )
        progress = (
            int(job.progress)
            if status_value == FileStatus.PROCESSING.value and job is not None
            else 100
            if status_value == FileStatus.SUCCESS.value
            else 0
        )
        return cls.model_validate(
            {
                "id": record.id,
                "knowledge_base_id": record.knowledge_base_id,
                "original_name": record.original_name,
                "stored_name": record.stored_name,
                "file_path": record.file_path,
                "file_type": record.file_type,
                "file_size": record.file_size,
                "md5": record.md5,
                "status": record.status,
                "chunk_count": record.chunk_count,
                "progress": progress,
                "has_active_vectors": record.has_active_vectors,
                "active_index_config_hash": record.active_index_config_hash,
                "error_message": record.error_message,
                "processing_job_id": record.processing_job_id,
                "last_successful_indexed_at": record.last_successful_indexed_at,
                "embedding_provider": settings.EMBEDDING_PROVIDER,
                "embedding_model": settings.EMBEDDING_MODEL,
                "embedding_dimension": settings.EMBEDDING_DIMENSION,
                "vector_metric": settings.VECTOR_DISTANCE_METRIC,
                "collection_name": (
                    knowledge_base.active_collection_name
                    if record.has_active_vectors
                    else None
                ),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )


class FileUploadResponse(FileRecordResponse):
    """Metadata returned after a file and its database row are persisted."""

    @classmethod
    def from_record(
        cls,
        record: Any,
        *,
        settings: Any,
        knowledge_base: Any,
        job: Any = None,
    ) -> Self:
        """Build an upload response from a SQLAlchemy record."""
        return cls.model_validate(
            FileRecordResponse.from_record(
                record,
                settings=settings,
                knowledge_base=knowledge_base,
                job=job,
            ).model_dump()
        )


class FileRecordPage(BaseModel):
    items: list[FileRecordResponse]
    total: int
    limit: int
    offset: int


class FileStatusResponse(BaseModel):
    """A compact file-processing status response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: FileStatus
    chunk_count: int = Field(ge=0)
    error_message: str | None
    updated_at: datetime

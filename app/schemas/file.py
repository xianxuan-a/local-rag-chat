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
    error_message: str | None
    last_successful_indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FileUploadResponse(FileRecordResponse):
    """Metadata returned after a file and its database row are persisted."""

    @classmethod
    def from_record(cls, record: Any) -> Self:
        """Build an upload response from a SQLAlchemy record."""
        return cls.model_validate(record)


class FileStatusResponse(BaseModel):
    """A compact file-processing status response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: FileStatus
    chunk_count: int = Field(ge=0)
    error_message: str | None
    updated_at: datetime

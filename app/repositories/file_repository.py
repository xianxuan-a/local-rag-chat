"""Data-access operations for uploaded-file records."""

from __future__ import annotations

from datetime import datetime

from app.models import (
    FileRecord,
    FileStatus,
    KnowledgeBase,
    RebuildStatus,
)
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session


class FileRepository:
    """Persist file metadata without owning transaction boundaries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        file_record: FileRecord | None = None,
        **values: object,
    ) -> FileRecord:
        if file_record is not None and values:
            raise ValueError("传入 FileRecord 时不能同时传入字段参数")
        record = file_record or FileRecord(**values)
        self.db.add(record)
        self.db.flush()
        self.db.refresh(record)
        return record

    def get_by_id(self, file_id: str) -> FileRecord | None:
        statement = select(FileRecord).where(FileRecord.id == str(file_id))
        return self.db.scalar(statement)

    def get_by_md5(
        self, knowledge_base_id: str, md5: str
    ) -> FileRecord | None:
        statement = select(FileRecord).where(
            FileRecord.knowledge_base_id == str(knowledge_base_id),
            FileRecord.md5 == md5,
        )
        return self.db.scalar(statement)

    def list_by_knowledge_base(
        self, knowledge_base_id: str
    ) -> list[FileRecord]:
        statement = (
            select(FileRecord)
            .where(FileRecord.knowledge_base_id == str(knowledge_base_id))
            .order_by(FileRecord.created_at.asc(), FileRecord.id.asc())
        )
        return list(self.db.scalars(statement).all())

    def update_status(
        self,
        file_id: str,
        status: FileStatus,
        *,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> FileRecord | None:
        file_record = self.get_by_id(file_id)
        if file_record is None:
            return None
        file_record.status = status
        if chunk_count is not None:
            file_record.chunk_count = chunk_count
        file_record.error_message = error_message
        self.db.flush()
        self.db.refresh(file_record)
        return file_record

    def claim_for_processing(self, file_id: str) -> FileRecord | None:
        """Atomically claim one eligible file while its KB is not rebuilding."""

        knowledge_base_available = exists(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id == FileRecord.knowledge_base_id,
                KnowledgeBase.rebuild_status != RebuildStatus.BUILDING,
            )
        )
        statement = (
            update(FileRecord)
            .where(
                FileRecord.id == str(file_id),
                FileRecord.status.in_(
                    (
                        FileStatus.PENDING,
                        FileStatus.FAILED,
                        FileStatus.SUCCESS,
                    )
                ),
                knowledge_base_available,
            )
            .values(status=FileStatus.PROCESSING, error_message=None)
            .execution_options(synchronize_session=False)
        )
        result = self.db.execute(statement)
        if result.rowcount != 1:
            return None
        self.db.flush()
        return self.get_by_id(file_id)

    def has_processing(self, knowledge_base_id: str) -> bool:
        statement = select(
            exists().where(
                FileRecord.knowledge_base_id == str(knowledge_base_id),
                FileRecord.status == FileStatus.PROCESSING,
            )
        )
        return bool(self.db.scalar(statement))

    def update_active_index(
        self,
        file_record: FileRecord,
        *,
        chunk_count: int,
        config_hash: str,
        indexed_at: datetime,
        update_task_status: bool = True,
    ) -> FileRecord:
        if update_task_status:
            file_record.status = FileStatus.SUCCESS
            file_record.error_message = None
        file_record.chunk_count = chunk_count
        file_record.has_active_vectors = chunk_count > 0
        file_record.active_index_config_hash = (
            config_hash if chunk_count > 0 else None
        )
        file_record.last_successful_indexed_at = (
            indexed_at if chunk_count > 0 else None
        )
        self.db.flush()
        return file_record

    def delete(self, file_record: FileRecord) -> FileRecord:
        self.db.delete(file_record)
        self.db.flush()
        return file_record

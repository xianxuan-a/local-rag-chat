"""Data-access contract for uploaded-file records."""

from __future__ import annotations

from app.core.exceptions import FeatureNotImplementedException
from app.models import FileRecord, FileStatus
from sqlalchemy.orm import Session


class FileRepository:
    """Persist initial upload records; later file operations remain explicit stubs."""

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
        _ = file_id
        raise FeatureNotImplementedException("文件详情查询功能尚未完成初始化")

    def get_by_md5(
        self, knowledge_base_id: str, md5: str
    ) -> FileRecord | None:
        _ = (knowledge_base_id, md5)
        raise FeatureNotImplementedException("文件 MD5 查询功能尚未完成初始化")

    def list_by_knowledge_base(
        self, knowledge_base_id: str
    ) -> list[FileRecord]:
        _ = knowledge_base_id
        raise FeatureNotImplementedException("文件列表功能尚未完成初始化")

    def update_status(
        self,
        file_id: str,
        status: FileStatus,
        *,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> FileRecord:
        _ = (file_id, status, chunk_count, error_message)
        raise FeatureNotImplementedException("文件状态更新功能尚未完成初始化")

    def delete(self, file_record: FileRecord) -> FileRecord:
        _ = file_record
        raise FeatureNotImplementedException("文件删除功能尚未完成初始化")

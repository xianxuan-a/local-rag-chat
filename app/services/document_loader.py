"""Deterministic parsing and cleaning for supported local documents."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.exceptions import (
    FileProcessException,
    ResourceNotFoundException,
    UnsupportedFileTypeException,
    ValidationException,
)
from app.core.logger import get_logger
from app.utils.file_utils import sanitize_filename
from app.utils.text_utils import clean_text


logger = get_logger(__name__)
SUPPORTED_FILE_TYPES = {".txt", ".json", ".csv", ".pdf"}
TEXT_ENCODINGS = ("utf-8-sig", "gb18030")


class DocumentLoaderService:
    """Parse TXT, JSON, CSV, and PDF files into cleaned documents."""

    def load_file(
        self,
        file_path: str | Path,
        *,
        file_id: str,
        knowledge_base_id: str,
        file_name: str | None = None,
        file_type: str | None = None,
        additional_metadata: Mapping[str, Any] | None = None,
    ) -> list[Document]:
        """Load one supported file with stable, non-path-based provenance."""
        path = Path(file_path)
        if not path.exists():
            raise ResourceNotFoundException("待解析文件不存在")
        if not path.is_file():
            raise FileProcessException("待解析路径不是普通文件")

        normalized_file_id = self._require_identity("file_id", file_id)
        normalized_kb_id = self._require_identity(
            "knowledge_base_id", knowledge_base_id
        )
        logical_name = self._resolve_file_name(path, file_name)
        normalized_type = self._resolve_file_type(path, file_type)
        base_metadata = dict(additional_metadata or {})
        base_metadata.update(
            {
                "file_id": normalized_file_id,
                "knowledge_base_id": normalized_kb_id,
                "file_name": logical_name,
                "file_type": normalized_type,
                "source": logical_name,
            }
        )

        if normalized_type == ".txt":
            return self._load_txt(path, base_metadata)
        if normalized_type == ".json":
            return self._load_json(path, base_metadata)
        if normalized_type == ".csv":
            return self._load_csv(path, base_metadata)
        return self._load_pdf(path, base_metadata)

    @staticmethod
    def _require_identity(field_name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationException(f"{field_name} 不能为空")
        return value.strip()

    @staticmethod
    def _resolve_file_name(path: Path, file_name: str | None) -> str:
        candidate = file_name if file_name is not None else path.name
        try:
            return sanitize_filename(candidate)
        except ValueError as exc:
            raise ValidationException(f"文件名无效：{exc}") from exc

    @staticmethod
    def _resolve_file_type(path: Path, file_type: str | None) -> str:
        raw_type = file_type or path.suffix
        normalized_type = raw_type.strip().lower()
        if normalized_type and not normalized_type.startswith("."):
            normalized_type = f".{normalized_type}"
        if normalized_type not in SUPPORTED_FILE_TYPES:
            raise UnsupportedFileTypeException(
                f"不支持的文档类型：{normalized_type or '无扩展名'}"
            )
        if path.suffix.lower() != normalized_type:
            raise ValidationException("文件类型与磁盘文件扩展名不一致")
        return normalized_type

    def _load_txt(self, path: Path, metadata: dict[str, Any]) -> list[Document]:
        text, encoding = self._read_text(path)
        return [
            self._build_document(
                text,
                {**metadata, "source_index": 0, "encoding": encoding},
            )
        ]

    def _load_json(self, path: Path, metadata: dict[str, Any]) -> list[Document]:
        text, encoding = self._read_text(path)
        try:
            parsed = json.loads(
                text,
                object_pairs_hook=self._unique_json_object,
                parse_constant=self._reject_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise FileProcessException("JSON 文件格式损坏") from exc

        if isinstance(parsed, dict):
            if not parsed:
                raise FileProcessException("JSON 文件没有有效内容")
            records: list[Any] = [parsed]
            is_array = False
        elif isinstance(parsed, list):
            if not parsed:
                raise FileProcessException("JSON 文件没有有效内容")
            records = parsed
            is_array = True
        else:
            raise FileProcessException("JSON 顶层必须是对象或数组")

        documents: list[Document] = []
        for index, record in enumerate(records):
            record_metadata = {
                **metadata,
                "source_index": index,
                "encoding": encoding,
            }
            if is_array:
                record_metadata["record_index"] = index
            canonical_text = json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            documents.append(self._build_document(canonical_text, record_metadata))
        return documents

    def _load_csv(self, path: Path, metadata: dict[str, Any]) -> list[Document]:
        text, encoding = self._read_text(path)
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", strict=True)
        try:
            header = next(reader)
            headers = [self._clean_csv_cell(value) for value in header]
            if not headers or any(not value for value in headers):
                raise FileProcessException("CSV 表头不能为空")
            if len(set(headers)) != len(headers):
                raise FileProcessException("CSV 表头不能重复")

            documents: list[Document] = []
            previous_line = reader.line_num
            for row in reader:
                physical_row = previous_line + 1
                previous_line = reader.line_num
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) != len(headers):
                    raise FileProcessException(
                        f"CSV 第 {physical_row} 行列数与表头不一致"
                    )
                values = [self._clean_csv_cell(value) for value in row]
                if not any(values):
                    continue
                content = "\n".join(
                    f"{header_name}: {value}" if value else f"{header_name}:"
                    for header_name, value in zip(headers, values, strict=True)
                )
                documents.append(
                    self._build_document(
                        content,
                        {
                            **metadata,
                            "source_index": len(documents),
                            "encoding": encoding,
                            "row": physical_row,
                        },
                    )
                )
        except csv.Error as exc:
            raise FileProcessException("CSV 文件格式损坏") from exc

        if not documents:
            raise FileProcessException("CSV 文件没有有效数据行")
        return documents

    def _load_pdf(self, path: Path, metadata: dict[str, Any]) -> list[Document]:
        try:
            with path.open("rb") as file_handle:
                reader = PdfReader(file_handle, strict=True)
                if reader.is_encrypted:
                    try:
                        decrypted = reader.decrypt("")
                    except Exception as exc:
                        raise FileProcessException("PDF 文件已加密且无法读取") from exc
                    if not decrypted:
                        raise FileProcessException("PDF 文件已加密且无法读取")

                total_pages = len(reader.pages)
                if total_pages == 0:
                    raise FileProcessException("PDF 文件没有页面")

                documents: list[Document] = []
                for page_index, page in enumerate(reader.pages):
                    try:
                        extracted = page.extract_text() or ""
                    except Exception as exc:
                        raise FileProcessException(
                            f"PDF 第 {page_index + 1} 页文本提取失败"
                        ) from exc
                    cleaned = clean_text(extracted)
                    if not cleaned:
                        logger.warning(
                            "PDF 页面没有可提取文本（file_id=%s, file_name=%s, page=%s）",
                            metadata["file_id"],
                            metadata["file_name"],
                            page_index + 1,
                        )
                        continue
                    documents.append(
                        Document(
                            page_content=cleaned,
                            metadata={
                                **metadata,
                                "source_index": page_index,
                                "page": page_index + 1,
                                "total_pages": total_pages,
                            },
                        )
                    )
        except FileProcessException:
            raise
        except (OSError, PdfReadError, ValueError) as exc:
            raise FileProcessException("PDF 文件损坏或无法读取") from exc

        if not documents:
            raise FileProcessException("PDF 文件未提取到有效文本")
        return documents

    @staticmethod
    def _read_text(path: Path) -> tuple[str, str]:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise FileProcessException("读取文档失败") from exc
        if not content:
            raise FileProcessException("文档内容为空")

        for encoding in TEXT_ENCODINGS:
            try:
                text = content.decode(encoding)
            except UnicodeDecodeError:
                continue
            if not clean_text(text):
                raise FileProcessException("文档清洗后没有有效内容")
            return text, encoding
        raise FileProcessException("文档编码无法识别，仅支持 UTF-8 和 GB18030")

    @staticmethod
    def _build_document(text: str, metadata: dict[str, Any]) -> Document:
        cleaned = clean_text(text)
        if not cleaned:
            raise FileProcessException("文档清洗后没有有效内容")
        return Document(page_content=cleaned, metadata=dict(metadata))

    @staticmethod
    def _clean_csv_cell(value: str) -> str:
        return clean_text(value).replace("\n", " ")

    @staticmethod
    def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON 包含重复字段：{key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError(f"JSON 包含非标准数值：{value}")

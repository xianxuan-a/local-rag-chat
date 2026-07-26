"""Configuration-driven deterministic document splitting."""

from collections.abc import Sequence
from copy import deepcopy
import json

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings, get_settings
from app.core.exceptions import FileProcessException, ValidationException
from app.services.hash_service import HashService


REQUIRED_METADATA = (
    "file_id",
    "knowledge_base_id",
    "file_name",
    "file_type",
    "source",
    "source_index",
)


class DocumentSplitterService:
    """Split cleaned documents using character-count settings."""

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        configured = settings or get_settings()
        resolved_size = configured.CHUNK_SIZE if chunk_size is None else chunk_size
        resolved_overlap = (
            configured.CHUNK_OVERLAP
            if chunk_overlap is None
            else chunk_overlap
        )
        self._validate_configuration(resolved_size, resolved_overlap)
        self.chunk_size = resolved_size
        self.chunk_overlap = resolved_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=resolved_size,
            chunk_overlap=resolved_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""],
            keep_separator=True,
            is_separator_regex=False,
            strip_whitespace=True,
        )

    def split_documents(self, documents: Sequence[Document]) -> list[Document]:
        """Return stable chunks while preserving independent source metadata."""
        if not documents:
            raise ValidationException("待切分文档不能为空")

        chunks: list[Document] = []
        for document in documents:
            if not isinstance(document, Document):
                raise ValidationException("待切分内容必须是 LangChain Document")
            if not document.page_content.strip():
                raise FileProcessException("待切分文档没有有效内容")
            self._validate_metadata(document.metadata)

            split_texts = self._splitter.split_text(document.page_content)
            if not split_texts:
                raise FileProcessException("文档切分后没有有效内容")
            for content in split_texts:
                if not content.strip():
                    raise FileProcessException("文档切分产生了空分块")
                chunk_index = len(chunks)
                metadata = deepcopy(document.metadata)
                metadata["chunk_index"] = chunk_index
                metadata["chunk_id"] = self._build_chunk_id(
                    metadata,
                    chunk_index,
                    content,
                )
                chunks.append(
                    Document(page_content=content, metadata=metadata)
                )
        return chunks

    @staticmethod
    def _validate_configuration(chunk_size: int, chunk_overlap: int) -> None:
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise ValidationException("chunk_size 必须是正整数")
        if isinstance(chunk_overlap, bool) or not isinstance(chunk_overlap, int):
            raise ValidationException("chunk_overlap 必须是非负整数")
        if chunk_size <= 0:
            raise ValidationException("chunk_size 必须大于 0")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValidationException("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    @staticmethod
    def _validate_metadata(metadata: dict[str, object]) -> None:
        for field_name in REQUIRED_METADATA:
            value = metadata.get(field_name)
            if field_name == "source_index":
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValidationException("source_index 必须是非负整数")
            elif not isinstance(value, str) or not value.strip():
                raise ValidationException(f"分块元数据缺少有效字段：{field_name}")

    def _build_chunk_id(
        self,
        metadata: dict[str, object],
        chunk_index: int,
        content: str,
    ) -> str:
        identity = json.dumps(
            {
                "knowledge_base_id": metadata["knowledge_base_id"],
                "file_id": metadata["file_id"],
                "source_index": metadata["source_index"],
                "chunk_index": chunk_index,
                "content": content,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"chunk_{HashService.calculate_text_md5(identity)}"

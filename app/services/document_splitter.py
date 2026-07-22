"""Document splitting contract for a later RAG implementation phase."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document


class DocumentSplitterService:
    """Reserved chunking service with an explicit overlap invariant."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, documents: Sequence["Document"]) -> list["Document"]:
        """Split documents according to the configured window."""
        raise NotImplementedError("文档切分功能尚未完成初始化")

"""Vector-store contract without model or Chroma initialization."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document


class VectorStoreService:
    """Reserved Chroma operations for the full RAG phase."""

    def add_documents(
        self,
        documents: Sequence["Document"],
        ids: Sequence[str] | None = None,
    ) -> list[str]:
        raise NotImplementedError("向量入库功能尚未完成初始化")

    def delete_by_file_id(self, file_id: str) -> None:
        raise NotImplementedError("按文件删除向量功能尚未完成初始化")

    def similarity_search(
        self,
        query: str,
        top_k: int = 4,
        score_threshold: float = 0.5,
    ) -> list[tuple["Document", float]]:
        raise NotImplementedError("向量相似度检索功能尚未完成初始化")

    def reset_collection(self) -> None:
        raise NotImplementedError("重置向量集合功能尚未完成初始化")

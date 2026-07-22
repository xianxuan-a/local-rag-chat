"""Knowledge-base retrieval contract."""

from app.schemas.chat import SourceReference


class RetrievalService:
    """Reserved orchestration layer for vector retrieval."""

    def retrieve(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int = 4,
        score_threshold: float = 0.5,
    ) -> list[SourceReference]:
        raise NotImplementedError("知识库检索功能尚未完成初始化")

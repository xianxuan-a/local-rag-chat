"""Initialization-phase RAG facade."""

from app.schemas.chat import ChatRequest, ChatResponse


class RagService:
    """Return an explicit placeholder without touching models or persistence."""

    def ask(self, request: ChatRequest) -> ChatResponse:
        """Acknowledge a validated request without running a RAG pipeline."""
        _ = request
        return ChatResponse(
            answer="RAG 问答服务尚未完成初始化",
            sources=[],
        )

"""RAG chat API route."""

from fastapi import APIRouter

from app.core.response import ApiResponse, success_response
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RagService


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ApiResponse[ChatResponse])
def chat(payload: ChatRequest):
    """Return the initialization-phase RAG placeholder."""
    return success_response(RagService().ask(payload))

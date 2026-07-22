"""Document loading contract for a later RAG implementation phase."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document


class DocumentLoaderService:
    """Reserved loader for TXT, PDF, CSV, and JSON files."""

    def load_file(self, file_path: str | Path) -> list["Document"]:
        """Load a supported file into LangChain documents."""
        raise NotImplementedError("文档解析功能尚未完成初始化")

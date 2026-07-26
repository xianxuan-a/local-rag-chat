"""Process-wide locks and shared RAG infrastructure."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Iterator

from starlette.requests import Request

from app.core.config import Settings
from app.core.exceptions import ConflictException
from app.services.vector_store_service import VectorStoreService


class RuntimeCoordinator:
    """Hold the single-process Chroma client and global mutation locks."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.collection_admin_lock = threading.RLock()
        self.vector_write_lock = threading.RLock()
        self.vector_store = VectorStoreService(
            settings,
            write_lock=self.vector_write_lock,
        )

    @contextmanager
    def admin_operation(self, operation: str) -> Iterator[None]:
        acquired = self.collection_admin_lock.acquire(blocking=False)
        if not acquired:
            raise ConflictException(
                "另一个知识库管理操作正在执行，请稍后重试",
                data={"operation": operation},
            )
        try:
            yield
        finally:
            self.collection_admin_lock.release()


def get_runtime_coordinator(request: Request) -> RuntimeCoordinator:
    runtime = getattr(request.app.state, "rag_runtime", None)
    if runtime is None:
        raise RuntimeError("RAG 运行时尚未初始化")
    return runtime

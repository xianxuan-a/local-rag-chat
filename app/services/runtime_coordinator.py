"""Process-wide write barrier, Chroma client, and mutation locks."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
from typing import Iterator

from starlette.requests import Request

from app.core.config import Settings
from app.core.product_settings import ProductSettingsManager, ProductSettingsSnapshot
from app.core.exceptions import ConflictException
from app.services.vector_store_service import VectorStoreService
from app.services.web_search_service import (
    UnconfiguredWebSearchProvider,
    WebPageFetcher,
    WebSearchProvider,
    WebSearchService,
)


class WriterPreferringBarrier:
    """Readers/writer barrier that blocks new readers once backup is waiting."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def shared(self, *, blocking: bool = False) -> Iterator[None]:
        with self._condition:
            if not blocking and (self._writer or self._waiting_writers):
                raise ConflictException("系统正在进入备份写屏障，暂时拒绝业务写入")
            while self._writer or self._waiting_writers:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._condition:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer = False
                self._condition.notify_all()


@dataclass(slots=True)
class ActiveChat:
    """Process-local cancellation state for one active chat generation."""

    assistant_message_id: str | None = None
    cancel_requested: bool = False


class RuntimeCoordinator:
    """Hold single-process Chroma infrastructure and operation coordination."""

    def __init__(
        self,
        settings: Settings,
        product_settings: ProductSettingsSnapshot | None = None,
        *,
        web_search_provider: WebSearchProvider | None = None,
        web_page_fetcher: WebPageFetcher | None = None,
    ) -> None:
        self.settings = settings
        self.product_settings = ProductSettingsManager(settings, product_settings)
        self.collection_admin_lock = threading.RLock()
        self.vector_write_lock = threading.RLock()
        self._chat_lock = threading.Lock()
        self._active_chats: dict[str, ActiveChat] = {}
        self.business_write_barrier = WriterPreferringBarrier()
        self.vector_store = VectorStoreService(
            settings,
            write_lock=self.vector_write_lock,
        )
        self.web_search_provider = (
            web_search_provider
            or UnconfiguredWebSearchProvider(
                settings.WEB_SEARCH_PROVIDER
            )
        )
        self.web_page_fetcher = (
            web_page_fetcher or WebPageFetcher(settings)
        )
        self.web_search = WebSearchService(
            self.web_search_provider,
            self.web_page_fetcher,
            settings,
        )

    def effective_settings(self) -> Settings:
        """Return one consistent settings object for a business operation."""

        return self.product_settings.effective_settings()

    def begin_chat(self, session_id: str) -> None:
        """Acquire the single active generation slot for one session."""

        resolved = str(session_id)
        with self._chat_lock:
            if resolved in self._active_chats:
                raise ConflictException(
                    "该会话已有回答正在生成，请等待完成或先停止",
                    data={"session_id": resolved},
                )
            self._active_chats[resolved] = ActiveChat()

    def bind_chat_message(
        self,
        session_id: str,
        assistant_message_id: str,
    ) -> None:
        """Bind cancellation to one exact answer, preventing stale stop requests."""

        resolved_session = str(session_id)
        with self._chat_lock:
            active = self._active_chats.get(resolved_session)
            if active is None:
                raise ConflictException("该会话当前没有正在生成的回答")
            active.assistant_message_id = str(assistant_message_id)

    def request_chat_cancel(
        self,
        session_id: str,
        assistant_message_id: str,
    ) -> bool:
        """Request cooperative cancellation for one exact active answer."""

        resolved_session = str(session_id)
        resolved_message = str(assistant_message_id)
        with self._chat_lock:
            active = self._active_chats.get(resolved_session)
            if (
                active is None
                or active.assistant_message_id != resolved_message
            ):
                return False
            active.cancel_requested = True
            return True

    def is_chat_cancel_requested(
        self,
        session_id: str,
        assistant_message_id: str,
    ) -> bool:
        resolved_session = str(session_id)
        resolved_message = str(assistant_message_id)
        with self._chat_lock:
            active = self._active_chats.get(resolved_session)
            return bool(
                active is not None
                and active.assistant_message_id == resolved_message
                and active.cancel_requested
            )

    def end_chat(self, session_id: str) -> None:
        with self._chat_lock:
            self._active_chats.pop(str(session_id), None)

    def is_chat_active(self, session_id: str) -> bool:
        with self._chat_lock:
            return str(session_id) in self._active_chats

    @contextmanager
    def business_write(self, operation: str) -> Iterator[None]:
        try:
            with self.business_write_barrier.shared(blocking=False):
                yield
        except ConflictException as exc:
            if exc.data is None:
                exc.data = {"operation": operation}
            raise

    @contextmanager
    def backup_exclusive(self) -> Iterator[None]:
        with self.business_write_barrier.exclusive():
            yield

    @contextmanager
    def admin_operation(self, operation: str) -> Iterator[None]:
        with self.business_write(operation):
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

    def close(self) -> None:
        """Release Chroma resources so offline backup/cutover can rename files."""

        client = self.vector_store._client
        if client is not None:
            system = getattr(client, "_system", None)
            stop = getattr(system, "stop", None)
            if callable(stop):
                stop()
            self.vector_store._client = None


def get_runtime_coordinator(request: Request) -> RuntimeCoordinator:
    runtime = getattr(request.app.state, "rag_runtime", None)
    if runtime is None:
        raise RuntimeError("RAG 运行时尚未初始化")
    return runtime

"""Atomic process-wide snapshots for database-backed product settings."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from app.core.config import Settings
from app.core.retrieval_modes import RetrievalMode


@dataclass(frozen=True, slots=True)
class ProductSettingsSnapshot:
    """The small, non-secret subset that may be changed at runtime."""

    chat_model: str | None
    retrieval_top_k: int
    retrieval_score_threshold: float | None
    rag_context_max_chars: int
    web_search_enabled: bool
    default_retrieval_mode: RetrievalMode
    retrieval_min_evidence_count: int
    retrieval_freshness_terms: tuple[str, ...]

    @classmethod
    def from_environment(cls, settings: Settings) -> "ProductSettingsSnapshot":
        return cls(
            chat_model=settings.CHAT_MODEL,
            retrieval_top_k=settings.RETRIEVAL_TOP_K,
            retrieval_score_threshold=settings.RETRIEVAL_SCORE_THRESHOLD,
            rag_context_max_chars=settings.RAG_CONTEXT_MAX_CHARS,
            web_search_enabled=settings.WEB_SEARCH_ENABLED,
            default_retrieval_mode=settings.DEFAULT_RETRIEVAL_MODE,
            retrieval_min_evidence_count=(
                settings.RETRIEVAL_MIN_EVIDENCE_COUNT
            ),
            retrieval_freshness_terms=tuple(
                settings.RETRIEVAL_FRESHNESS_TERMS
            ),
        )

    def as_settings_update(self) -> dict[str, object]:
        return {
            "CHAT_MODEL": self.chat_model,
            "RETRIEVAL_TOP_K": self.retrieval_top_k,
            "RETRIEVAL_SCORE_THRESHOLD": self.retrieval_score_threshold,
            "RAG_CONTEXT_MAX_CHARS": self.rag_context_max_chars,
            "WEB_SEARCH_ENABLED": self.web_search_enabled,
            "DEFAULT_RETRIEVAL_MODE": self.default_retrieval_mode,
            "RETRIEVAL_MIN_EVIDENCE_COUNT": (
                self.retrieval_min_evidence_count
            ),
            "RETRIEVAL_FRESHNESS_TERMS": list(
                self.retrieval_freshness_terms
            ),
        }


class ProductSettingsManager:
    """Replace and read immutable snapshots without partial field updates."""

    def __init__(
        self,
        base_settings: Settings,
        initial: ProductSettingsSnapshot | None = None,
    ) -> None:
        self._base_settings = base_settings
        self._snapshot = initial or ProductSettingsSnapshot.from_environment(
            base_settings
        )
        self._persistent_override = initial is not None
        self._lock = RLock()

    def snapshot(self) -> ProductSettingsSnapshot:
        with self._lock:
            if self._persistent_override:
                return self._snapshot
        return ProductSettingsSnapshot.from_environment(self._base_settings)

    def replace(self, snapshot: ProductSettingsSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._persistent_override = True

    def effective_settings(self) -> Settings:
        snapshot = self.snapshot()
        return self._base_settings.model_copy(
            update=snapshot.as_settings_update()
        )

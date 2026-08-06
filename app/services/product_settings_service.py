"""Load, validate, persist, and publish supported product settings."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.product_settings import ProductSettingsManager, ProductSettingsSnapshot
from app.core.retrieval_modes import RetrievalMode
from app.repositories.product_settings_repository import ProductSettingsRepository
from app.schemas.settings import ProductSettingsResponse, ProductSettingsUpdate


class ProductSettingsService:
    def __init__(self, db: Session, base_settings: Settings) -> None:
        self.db = db
        self.base_settings = base_settings
        self.repository = ProductSettingsRepository(db)

    def load_snapshot(self) -> ProductSettingsSnapshot:
        record = self.repository.get()
        if record is None:
            return ProductSettingsSnapshot.from_environment(self.base_settings)
        return ProductSettingsSnapshot(
            chat_model=record.chat_model,
            retrieval_top_k=record.retrieval_top_k,
            retrieval_score_threshold=record.retrieval_score_threshold,
            rag_context_max_chars=record.rag_context_max_chars,
            web_search_enabled=record.web_search_enabled,
            default_retrieval_mode=RetrievalMode(
                record.default_retrieval_mode
            ),
            retrieval_min_evidence_count=record.retrieval_min_evidence_count,
            retrieval_freshness_terms=tuple(
                record.retrieval_freshness_terms
            ),
        )

    def has_persistent_settings(self) -> bool:
        return self.repository.get() is not None

    def response(
        self,
        manager: ProductSettingsManager,
        *,
        current_user_role: str,
        web_search_provider: str | None = None,
        web_search_provider_configured: bool | None = None,
    ) -> ProductSettingsResponse:
        record = self.repository.get()
        snapshot = manager.snapshot()
        return ProductSettingsResponse(
            chat_model=snapshot.chat_model,
            retrieval_top_k=snapshot.retrieval_top_k,
            retrieval_score_threshold=snapshot.retrieval_score_threshold,
            rag_context_max_chars=snapshot.rag_context_max_chars,
            web_search_enabled=snapshot.web_search_enabled,
            default_retrieval_mode=snapshot.default_retrieval_mode,
            retrieval_min_evidence_count=(
                snapshot.retrieval_min_evidence_count
            ),
            retrieval_freshness_terms=list(
                snapshot.retrieval_freshness_terms
            ),
            web_search_provider=(
                web_search_provider
                if web_search_provider is not None
                else self.base_settings.WEB_SEARCH_PROVIDER
            ),
            web_search_provider_configured=(
                web_search_provider_configured
                if web_search_provider_configured is not None
                else False
            ),
            web_search_allowed_for_current_user=(
                current_user_role
                in self.base_settings.WEB_SEARCH_ALLOWED_ROLES
            ),
            embedding_provider=self.base_settings.EMBEDDING_PROVIDER,
            embedding_model=self.base_settings.EMBEDDING_MODEL,
            embedding_dimension=self.base_settings.EMBEDDING_DIMENSION,
            vector_metric=self.base_settings.VECTOR_DISTANCE_METRIC,
            dashscope_api_key_configured=bool(
                self.base_settings.DASHSCOPE_API_KEY.get_secret_value()
            ),
            source="persistent" if record is not None else "environment",
            updated_at=record.updated_at if record is not None else None,
        )

    def update(
        self,
        payload: ProductSettingsUpdate,
        *,
        updated_by_id: str,
        manager: ProductSettingsManager,
        web_search_provider: str | None = None,
        web_search_provider_configured: bool | None = None,
    ) -> ProductSettingsResponse:
        snapshot = ProductSettingsSnapshot(
            chat_model=payload.chat_model,
            retrieval_top_k=payload.retrieval_top_k,
            retrieval_score_threshold=payload.retrieval_score_threshold,
            rag_context_max_chars=payload.rag_context_max_chars,
            web_search_enabled=payload.web_search_enabled,
            default_retrieval_mode=payload.default_retrieval_mode,
            retrieval_min_evidence_count=(
                payload.retrieval_min_evidence_count
            ),
            retrieval_freshness_terms=tuple(
                payload.retrieval_freshness_terms
            ),
        )
        try:
            self.repository.save(
                chat_model=snapshot.chat_model,
                retrieval_top_k=snapshot.retrieval_top_k,
                retrieval_score_threshold=snapshot.retrieval_score_threshold,
                rag_context_max_chars=snapshot.rag_context_max_chars,
                web_search_enabled=snapshot.web_search_enabled,
                default_retrieval_mode=(
                    snapshot.default_retrieval_mode.value
                ),
                retrieval_min_evidence_count=(
                    snapshot.retrieval_min_evidence_count
                ),
                retrieval_freshness_terms=list(
                    snapshot.retrieval_freshness_terms
                ),
                updated_by_id=updated_by_id,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        manager.replace(snapshot)
        return self.response(
            manager,
            current_user_role="ADMIN",
            web_search_provider=web_search_provider,
            web_search_provider_configured=(
                web_search_provider_configured
            ),
        )

"""Mode policy and local/web retrieval orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, replace
from hashlib import sha256
import time
from uuid import NAMESPACE_URL, uuid5

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.observability import (
    RETRIEVAL_MODE_DECISIONS,
    RETRIEVAL_SOURCE_COUNT,
    RETRIEVAL_STAGE_DURATION,
    WEB_SEARCH_OUTCOMES,
)
from app.core.retrieval_modes import (
    KnowledgeBaseWebPolicy,
    RetrievalMode,
    WebSearchStatus,
    WebTriggerReason,
)
from app.schemas.chat import ChatRequest, RetrievalAudit
from app.services.evidence_sufficiency_service import EvidenceSufficiencyService
from app.services.retrieval_service import RetrievedChunk, RetrievalService
from app.services.untrusted_content_service import UntrustedContentSanitizer
from app.services.web_search_service import (
    WebPageEvidence,
    WebSearchOutcome,
    WebSearchService,
)
from app.utils.text_utils import clean_text, truncate_text


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalModeDecision:
    requested_mode: RetrievalMode
    effective_mode: RetrievalMode
    initial_web_status: WebSearchStatus
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalBundle:
    audit: RetrievalAudit
    knowledge_chunks: tuple[RetrievedChunk, ...]
    web_pages: tuple[WebPageEvidence, ...]
    local_retrieval_duration_ms: float
    web_search_duration_ms: float
    web_fetch_duration_ms: float
    provider_status: str | None
    query_digest: str | None = None
    local_error_type: str | None = None
    excluded_reasons: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return bool(self.knowledge_chunks or self.web_pages)

    def retrieved_chunks(self) -> tuple[RetrievedChunk, ...]:
        """Return one generation input while preserving provenance type."""

        web_chunks = tuple(
            RetrievedChunk(
                content=page.content,
                file_id=uuid5(NAMESPACE_URL, page.url),
                file_name=page.title,
                chunk_id=(
                    "web_"
                    + sha256(page.url.encode("utf-8")).hexdigest()[:32]
                ),
                content_preview=page.content_preview,
                score=page.quality_score,
                metadata=dict(page.metadata),
                source_type="web",
                title=page.title,
                url=page.url,
                domain=page.domain,
                published_at=page.published_at,
                accessed_at=page.accessed_at,
            )
            for page in self.web_pages
        )
        return (*self.knowledge_chunks, *web_chunks)


class RetrievalModePolicy:
    """Resolve the effective mode from server-owned policy."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve(
        self,
        requested_mode: RetrievalMode | None,
        *,
        user_role: str,
        knowledge_base_policy: str,
    ) -> RetrievalModeDecision:
        requested = requested_mode or self.settings.DEFAULT_RETRIEVAL_MODE
        if requested == RetrievalMode.KNOWLEDGE_ONLY:
            return RetrievalModeDecision(
                requested,
                RetrievalMode.KNOWLEDGE_ONLY,
                WebSearchStatus.NOT_REQUESTED,
            )
        if not self.settings.WEB_SEARCH_ENABLED:
            return RetrievalModeDecision(
                requested,
                RetrievalMode.KNOWLEDGE_ONLY,
                WebSearchStatus.BLOCKED_BY_POLICY,
                "global_web_search_disabled",
            )
        if user_role not in self.settings.WEB_SEARCH_ALLOWED_ROLES:
            return RetrievalModeDecision(
                requested,
                RetrievalMode.KNOWLEDGE_ONLY,
                WebSearchStatus.BLOCKED_BY_POLICY,
                "role_web_search_denied",
            )
        policy = KnowledgeBaseWebPolicy(knowledge_base_policy)
        if policy == KnowledgeBaseWebPolicy.DENY:
            return RetrievalModeDecision(
                requested,
                RetrievalMode.KNOWLEDGE_ONLY,
                WebSearchStatus.BLOCKED_BY_POLICY,
                "knowledge_base_web_search_denied",
            )
        return RetrievalModeDecision(
            requested,
            requested,
            WebSearchStatus.NOT_REQUESTED,
        )


class RetrievalOrchestrator:
    """Run the exact retrieval workflow selected by the effective mode."""

    def __init__(
        self,
        retrieval_service: RetrievalService,
        web_search_service: WebSearchService,
        settings: Settings,
        *,
        content_sanitizer: UntrustedContentSanitizer | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.web_search_service = web_search_service
        self.settings = settings
        self.mode_policy = RetrievalModePolicy(settings)
        self.sufficiency = EvidenceSufficiencyService(settings)
        self.content_sanitizer = (
            content_sanitizer or UntrustedContentSanitizer()
        )

    def retrieve(
        self,
        request: ChatRequest,
        *,
        user_role: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> RetrievalBundle:
        cancel_check = cancel_check or (lambda: False)
        knowledge_base = self.retrieval_service.knowledge_bases.get_by_id(
            str(request.knowledge_base_id)
        )
        if knowledge_base is None:
            # Preserve the existing retrieval service's public error semantics.
            self._retrieve_local(request)
            raise AssertionError("unreachable")
        decision = self.mode_policy.resolve(
            request.mode,
            user_role=user_role,
            knowledge_base_policy=knowledge_base.web_access_policy,
        )
        if decision.effective_mode == RetrievalMode.KNOWLEDGE_ONLY:
            chunks, duration, exclusions = self._retrieve_local(request)
            return self._bundle(
                decision,
                chunks,
                (),
                local_duration=duration,
                web_outcome=WebSearchOutcome(
                    status=decision.initial_web_status,
                    fallback_reason=decision.fallback_reason,
                ),
                excluded_reasons=exclusions,
            )
        if decision.effective_mode == RetrievalMode.KNOWLEDGE_FIRST:
            return self._knowledge_first(
                request,
                decision,
                cancel_check=cancel_check,
            )
        return self._hybrid(
            request,
            decision,
            cancel_check=cancel_check,
        )

    def _knowledge_first(
        self,
        request: ChatRequest,
        decision: RetrievalModeDecision,
        *,
        cancel_check: Callable[[], bool],
    ) -> RetrievalBundle:
        chunks: tuple[RetrievedChunk, ...] = ()
        exclusions: tuple[str, ...] = ()
        local_error: Exception | None = None
        local_started = time.perf_counter()
        try:
            chunks, _, exclusions = self._retrieve_local(request)
        except Exception as exc:
            local_error = exc
        local_duration = (time.perf_counter() - local_started) * 1000
        sufficiency = self.sufficiency.evaluate(
            request.question,
            chunks,
            retrieval_failed=local_error is not None,
        )
        if sufficiency.sufficient:
            return self._bundle(
                decision,
                chunks,
                (),
                local_duration=local_duration,
                web_outcome=WebSearchOutcome(
                    status=WebSearchStatus.NOT_REQUESTED
                ),
                local_error=local_error,
                excluded_reasons=exclusions,
            )
        if cancel_check():
            return self._cancelled_bundle(
                decision,
                chunks,
                local_duration,
                local_error,
                exclusions,
            )
        web_outcome = self.web_search_service.search(
            request.question,
            cancel_check=cancel_check,
        )
        pages, duplicate_exclusions = self._remove_cross_source_duplicates(
            chunks,
            web_outcome.evidence,
        )
        web_outcome = replace(web_outcome, evidence=pages)
        trigger_reason = sufficiency.reason
        fallback = web_outcome.fallback_reason
        if local_error is not None and pages:
            fallback = "local_retrieval_failed"
        elif not pages and chunks:
            fallback = fallback or "web_unavailable_local_fallback"
        return self._bundle(
            decision,
            chunks,
            pages,
            local_duration=local_duration,
            web_outcome=web_outcome,
            trigger_reason=trigger_reason,
            fallback_reason=fallback,
            local_error=local_error,
            excluded_reasons=(
                *exclusions,
                *duplicate_exclusions,
            ),
        )

    def _hybrid(
        self,
        request: ChatRequest,
        decision: RetrievalModeDecision,
        *,
        cancel_check: Callable[[], bool],
    ) -> RetrievalBundle:
        executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="hybrid-retrieval",
        )
        local_future = executor.submit(self._retrieve_local, request)
        web_future = executor.submit(
            self.web_search_service.search,
            request.question,
            cancel_check=cancel_check,
        )
        deadline = time.monotonic() + self.settings.WEB_TOTAL_TIMEOUT_SECONDS
        local_error: Exception | None = None
        local_duration = 0.0
        exclusions: tuple[str, ...] = ()
        chunks: tuple[RetrievedChunk, ...] = ()
        try:
            remaining = max(0.001, deadline - time.monotonic())
            try:
                chunks, local_duration, exclusions = local_future.result(
                    timeout=remaining
                )
            except Exception as exc:
                local_error = exc
            remaining = max(0.001, deadline - time.monotonic())
            try:
                web_outcome = web_future.result(timeout=remaining)
            except TimeoutError:
                web_outcome = WebSearchOutcome(
                    status=WebSearchStatus.TIMEOUT,
                    search_triggered=True,
                    fallback_reason="web_total_timeout",
                    provider_status="timeout",
                )
            except Exception:
                web_outcome = WebSearchOutcome(
                    status=WebSearchStatus.FAILED,
                    search_triggered=True,
                    fallback_reason="web_search_failed",
                    provider_status="failed",
                )
        finally:
            local_future.cancel()
            web_future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        pages, duplicate_exclusions = self._remove_cross_source_duplicates(
            chunks,
            web_outcome.evidence,
        )
        web_outcome = replace(web_outcome, evidence=pages)
        fallback = web_outcome.fallback_reason
        if local_error is not None and pages:
            fallback = "local_retrieval_failed"
        elif not pages and chunks:
            fallback = fallback or "web_unavailable_local_fallback"
        elif pages and not chunks and local_error is not None:
            fallback = "local_retrieval_failed"
        return self._bundle(
            decision,
            chunks,
            pages,
            local_duration=local_duration,
            web_outcome=web_outcome,
            trigger_reason=WebTriggerReason.HYBRID_REQUESTED,
            fallback_reason=fallback,
            local_error=local_error,
            excluded_reasons=(
                *exclusions,
                *duplicate_exclusions,
            ),
        )

    def _retrieve_local(
        self,
        request: ChatRequest,
    ) -> tuple[
        tuple[RetrievedChunk, ...],
        float,
        tuple[str, ...],
    ]:
        started = time.perf_counter()
        chunks = self.retrieval_service.retrieve_chunks(
            knowledge_base_id=str(request.knowledge_base_id),
            query=request.question,
            top_k=request.top_k,
            require_active_index=True,
        )
        duration = (time.perf_counter() - started) * 1000
        safe_chunks: list[RetrievedChunk] = []
        exclusions: list[str] = []
        for chunk in chunks:
            sanitized = self.content_sanitizer.sanitize(chunk.content)
            exclusions.extend(sanitized.excluded_reasons)
            if not sanitized.content:
                continue
            safe_chunks.append(
                replace(
                    chunk,
                    content=sanitized.content,
                    content_preview=truncate_text(
                        sanitized.content,
                        1000,
                    ),
                    metadata={
                        **chunk.metadata,
                        "injection_segments_removed": (
                            sanitized.suspicious_segment_count
                        ),
                    },
                )
            )
        return tuple(safe_chunks), duration, tuple(exclusions)

    @staticmethod
    def _remove_cross_source_duplicates(
        chunks: Sequence[RetrievedChunk],
        pages: Sequence[WebPageEvidence],
    ) -> tuple[tuple[WebPageEvidence, ...], tuple[str, ...]]:
        local_hashes = {
            sha256(
                clean_text(chunk.content).casefold().encode("utf-8")
            ).hexdigest()
            for chunk in chunks
        }
        retained: list[WebPageEvidence] = []
        exclusions: list[str] = []
        for page in pages:
            digest = sha256(
                clean_text(page.content).casefold().encode("utf-8")
            ).hexdigest()
            if digest in local_hashes:
                exclusions.append("duplicate_of_knowledge_source")
                continue
            retained.append(page)
        return tuple(retained), tuple(exclusions)

    @staticmethod
    def _bundle(
        decision: RetrievalModeDecision,
        chunks: Sequence[RetrievedChunk],
        pages: Sequence[WebPageEvidence],
        *,
        local_duration: float,
        web_outcome: WebSearchOutcome,
        trigger_reason: WebTriggerReason | None = None,
        fallback_reason: str | None = None,
        local_error: Exception | None = None,
        excluded_reasons: Sequence[str] = (),
    ) -> RetrievalBundle:
        audit = RetrievalAudit(
            requested_mode=decision.requested_mode,
            effective_mode=decision.effective_mode,
            web_search_triggered=web_outcome.search_triggered,
            web_search_status=web_outcome.status,
            web_trigger_reason=(
                trigger_reason.value
                if trigger_reason is not None
                else None
            ),
            knowledge_source_count=len(chunks),
            web_source_count=len(pages),
            fallback_reason=(
                fallback_reason
                or web_outcome.fallback_reason
                or decision.fallback_reason
            ),
        )
        provider_status = web_outcome.provider_status or "not_requested"
        RETRIEVAL_MODE_DECISIONS.labels(
            decision.requested_mode.value,
            decision.effective_mode.value,
        ).inc()
        WEB_SEARCH_OUTCOMES.labels(
            web_outcome.status.value,
            provider_status,
        ).inc()
        RETRIEVAL_STAGE_DURATION.labels("knowledge").observe(
            max(0.0, local_duration) / 1000
        )
        RETRIEVAL_STAGE_DURATION.labels("web_search").observe(
            max(0.0, web_outcome.search_duration_ms) / 1000
        )
        RETRIEVAL_STAGE_DURATION.labels("web_fetch").observe(
            max(0.0, web_outcome.fetch_duration_ms) / 1000
        )
        RETRIEVAL_SOURCE_COUNT.labels("knowledge_base").observe(len(chunks))
        RETRIEVAL_SOURCE_COUNT.labels("web").observe(len(pages))
        logger.info(
            "retrieval_decision requested_mode=%s effective_mode=%s "
            "web_status=%s web_triggered=%s knowledge_sources=%s "
            "web_sources=%s provider_status=%s fallback_reason=%s "
            "local_ms=%.3f web_search_ms=%.3f web_fetch_ms=%.3f "
            "query_digest=%s",
            decision.requested_mode.value,
            decision.effective_mode.value,
            web_outcome.status.value,
            web_outcome.search_triggered,
            len(chunks),
            len(pages),
            provider_status,
            audit.fallback_reason or "none",
            local_duration,
            web_outcome.search_duration_ms,
            web_outcome.fetch_duration_ms,
            web_outcome.query_digest or "not_requested",
        )
        return RetrievalBundle(
            audit=audit,
            knowledge_chunks=tuple(chunks),
            web_pages=tuple(pages),
            local_retrieval_duration_ms=local_duration,
            web_search_duration_ms=web_outcome.search_duration_ms,
            web_fetch_duration_ms=web_outcome.fetch_duration_ms,
            provider_status=web_outcome.provider_status,
            query_digest=web_outcome.query_digest,
            local_error_type=(
                type(local_error).__name__
                if local_error is not None
                else None
            ),
            excluded_reasons=tuple(
                (*excluded_reasons, *web_outcome.excluded_reasons)
            ),
        )

    @staticmethod
    def _cancelled_bundle(
        decision: RetrievalModeDecision,
        chunks: Sequence[RetrievedChunk],
        local_duration: float,
        local_error: Exception | None,
        exclusions: Sequence[str],
    ) -> RetrievalBundle:
        return RetrievalOrchestrator._bundle(
            decision,
            chunks,
            (),
            local_duration=local_duration,
            web_outcome=WebSearchOutcome(
                status=WebSearchStatus.FAILED,
                fallback_reason="client_cancelled",
                provider_status="cancelled",
            ),
            local_error=local_error,
            excluded_reasons=exclusions,
        )

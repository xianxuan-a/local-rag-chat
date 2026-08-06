"""Shared retrieval-mode, policy, and web-status vocabulary."""

from __future__ import annotations

from enum import StrEnum


class RetrievalMode(StrEnum):
    """Public retrieval modes used by API, persistence, and logs."""

    KNOWLEDGE_ONLY = "knowledge_only"
    KNOWLEDGE_FIRST = "knowledge_first"
    HYBRID = "hybrid"


class KnowledgeBaseWebPolicy(StrEnum):
    """Knowledge-base override applied beneath global and role policy."""

    INHERIT = "inherit"
    ALLOW = "allow"
    DENY = "deny"


class WebSearchStatus(StrEnum):
    """Auditable outcome of the optional external-search branch."""

    NOT_REQUESTED = "not_requested"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    NOT_CONFIGURED = "not_configured"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    QUERY_REJECTED = "query_rejected"


class WebTriggerReason(StrEnum):
    """Deterministic reasons that may cause an external search."""

    NO_RESULTS = "no_results"
    LOW_RELEVANCE = "low_relevance"
    INSUFFICIENT_COUNT = "insufficient_count"
    FRESHNESS_REQUIRED = "freshness_required"
    ENTITY_COVERAGE_INSUFFICIENT = "entity_coverage_insufficient"
    LOCAL_RETRIEVAL_FAILED = "local_retrieval_failed"
    HYBRID_REQUESTED = "hybrid_requested"


DEFAULT_FRESHNESS_TERMS = (
    "今天",
    "当前",
    "目前",
    "最近",
    "最新",
    "现价",
    "现任",
    "刚刚",
    "今年政策",
    "today",
    "current",
    "currently",
    "recent",
    "recently",
    "latest",
    "now",
    "this year",
)


ONLINE_RETRIEVAL_MODES = frozenset(
    (RetrievalMode.KNOWLEDGE_FIRST, RetrievalMode.HYBRID)
)

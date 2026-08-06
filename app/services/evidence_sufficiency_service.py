"""Deterministic local-evidence sufficiency decisions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from app.core.config import Settings
from app.core.retrieval_modes import WebTriggerReason
from app.services.retrieval_service import RetrievedChunk


_QUOTED_TERM = re.compile(r"[\"“'‘]([^\"”'’]{2,80})[\"”'’]")
_YEAR_OR_DATE = re.compile(
    r"\b(?:19|20)\d{2}(?:[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?)?\b"
)
_MODEL_OR_VERSION = re.compile(
    r"\b(?=[A-Za-z0-9._-]{2,40}\b)(?=[A-Za-z0-9._-]*[A-Za-z])"
    r"(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9._-]+\b"
)


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyDecision:
    sufficient: bool
    reason: WebTriggerReason | None
    best_score: float | None
    evidence_count: int
    uncovered_constraints: tuple[str, ...] = ()


class EvidenceSufficiencyService:
    """Use reproducible rules instead of a generation-model decision."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        question: str,
        chunks: Sequence[RetrievedChunk],
        *,
        retrieval_failed: bool = False,
    ) -> EvidenceSufficiencyDecision:
        if retrieval_failed:
            return EvidenceSufficiencyDecision(
                False,
                WebTriggerReason.LOCAL_RETRIEVAL_FAILED,
                None,
                0,
            )
        if not chunks:
            return EvidenceSufficiencyDecision(
                False,
                WebTriggerReason.NO_RESULTS,
                None,
                0,
            )
        best_score = max(chunk.score for chunk in chunks)
        folded_question = question.casefold()
        if any(
            term.casefold() in folded_question
            for term in self.settings.RETRIEVAL_FRESHNESS_TERMS
        ):
            return EvidenceSufficiencyDecision(
                False,
                WebTriggerReason.FRESHNESS_REQUIRED,
                best_score,
                len(chunks),
            )
        threshold = self.settings.RETRIEVAL_SCORE_THRESHOLD
        if threshold is not None and best_score < threshold:
            return EvidenceSufficiencyDecision(
                False,
                WebTriggerReason.LOW_RELEVANCE,
                best_score,
                len(chunks),
            )
        if len(chunks) < self.settings.RETRIEVAL_MIN_EVIDENCE_COUNT:
            return EvidenceSufficiencyDecision(
                False,
                WebTriggerReason.INSUFFICIENT_COUNT,
                best_score,
                len(chunks),
            )
        constraints = self._constraints(question)
        if constraints:
            evidence = "\n".join(chunk.content for chunk in chunks).casefold()
            uncovered = tuple(
                constraint
                for constraint in constraints
                if constraint.casefold() not in evidence
            )
            if uncovered:
                return EvidenceSufficiencyDecision(
                    False,
                    WebTriggerReason.ENTITY_COVERAGE_INSUFFICIENT,
                    best_score,
                    len(chunks),
                    uncovered,
                )
        return EvidenceSufficiencyDecision(
            True,
            None,
            best_score,
            len(chunks),
        )

    @staticmethod
    def _constraints(question: str) -> tuple[str, ...]:
        ordered: list[str] = []
        for pattern in (_QUOTED_TERM, _YEAR_OR_DATE, _MODEL_OR_VERSION):
            for match in pattern.finditer(question):
                value = (
                    match.group(1)
                    if match.lastindex
                    else match.group(0)
                ).strip()
                if value and value.casefold() not in {
                    item.casefold() for item in ordered
                }:
                    ordered.append(value)
        return tuple(ordered)

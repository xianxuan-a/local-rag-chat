"""Deterministic, network-free test doubles for vector services."""

from __future__ import annotations

from hashlib import sha256
import math

from langchain_core.embeddings import Embeddings


class FakeEmbedding(Embeddings):
    """Produce stable normalized vectors and expose call counts."""

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension
        self.document_calls = 0
        self.query_calls = 0

    def _vector(self, text: str) -> list[float]:
        digest = sha256(text.encode("utf-8")).digest()
        first = int.from_bytes(digest[:2], "big") % self.dimension
        second = int.from_bytes(digest[2:4], "big") % self.dimension
        vector = [0.0] * self.dimension
        vector[first] = 1.0
        vector[second] += 0.5
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._vector(text)

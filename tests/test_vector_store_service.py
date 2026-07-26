"""Persistent Chroma contract tests using only precomputed fake vectors."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
import pytest

from app.core.exceptions import VectorStoreException
from app.services.embedding_service import EmbeddingConfig
from app.services.vector_store_service import VectorStoreService
from tests.fakes import FakeEmbedding


def _document(kb_id: str, file_id: str, chunk_id: str, text: str) -> Document:
    return Document(
        page_content=text,
        metadata={
            "knowledge_base_id": kb_id,
            "file_id": file_id,
            "file_name": "source.txt",
            "file_type": ".txt",
            "source": "source.txt",
            "source_index": 0,
            "chunk_index": int(chunk_id.rsplit("_", 1)[-1]),
            "chunk_id": chunk_id,
        },
    )


def test_collection_contract_idempotent_replace_and_persistence(
    test_settings,
) -> None:
    fake = FakeEmbedding()
    store = VectorStoreService(
        test_settings,
        embedding_factory=lambda _: fake,
    )
    config = store.current_config
    kb_id = str(uuid4())
    file_id = str(uuid4())
    name, generation = store.generate_collection_name(
        kb_id, config.config_hash, generation="0123456789ab"
    )
    collection = store.create_collection(
        name=name,
        knowledge_base_id=kb_id,
        config=config,
        generation=generation,
    )

    assert collection.configuration["hnsw"]["space"] == "cosine"
    assert collection.configuration["embedding_function"] is None
    assert collection.metadata["embedding_protocol_version"] == (
        "dashscope-text-embedding-v1"
    )
    assert name.endswith("_0123456789ab")

    first = [
        _document(kb_id, file_id, "chunk_0", "alpha"),
        _document(kb_id, file_id, "chunk_1", "beta"),
    ]
    first_vectors = store.embed_documents(first, config)
    store.replace_file_documents(
        collection_name=name,
        knowledge_base_id=kb_id,
        file_id=file_id,
        documents=first,
        embeddings=first_vectors,
        config=config,
        role="building",
    )
    assert collection.count() == 2

    second = [_document(kb_id, file_id, "chunk_0", "alpha changed")]
    store.replace_file_documents(
        collection_name=name,
        knowledge_base_id=kb_id,
        file_id=file_id,
        documents=second,
        embeddings=store.embed_documents(second, config),
        config=config,
        role="building",
    )
    assert collection.count() == 1
    snapshot = store.snapshot_file(
        name,
        knowledge_base_id=kb_id,
        file_id=file_id,
        expected_config_hash=config.config_hash,
    )
    assert snapshot.documents == ["alpha changed"]
    assert len(snapshot.embeddings[0]) == 1024
    assert snapshot.ids == [
        store.vector_id(kb_id, file_id, "chunk_0")
    ]

    reloaded = VectorStoreService(
        test_settings,
        embedding_factory=lambda _: FakeEmbedding(),
    )
    persisted = reloaded.get_collection(
        name,
        knowledge_base_id=kb_id,
        expected_config_hash=config.config_hash,
        role="building",
    )
    assert persisted.count() == 1
    assert persisted.configuration["hnsw"]["space"] == "cosine"
    assert persisted.configuration["embedding_function"] is None


def test_negative_cosine_score_is_not_clamped_to_zero(test_settings) -> None:
    class OppositeQueryEmbedding(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise AssertionError("document embedding is precomputed in this test")

        def embed_query(self, text: str) -> list[float]:
            return [-1.0] + [0.0] * 1023

    store = VectorStoreService(
        test_settings,
        embedding_factory=lambda _: OppositeQueryEmbedding(),
    )
    config = store.current_config
    kb_id = str(uuid4())
    file_id = str(uuid4())
    name, generation = store.generate_collection_name(kb_id, config.config_hash)
    store.create_collection(
        name=name,
        knowledge_base_id=kb_id,
        config=config,
        generation=generation,
    )
    document = _document(kb_id, file_id, "chunk_0", "positive")
    store.replace_file_documents(
        collection_name=name,
        knowledge_base_id=kb_id,
        file_id=file_id,
        documents=[document],
        embeddings=[[1.0] + [0.0] * 1023],
        config=config,
        role="building",
    )
    store.set_lifecycle(name, "ACTIVE")

    results = store.similarity_search(
        "opposite",
        collection_name=name,
        knowledge_base_id=kb_id,
        config_hash=config.config_hash,
    )

    assert len(results) == 1
    assert results[0].score == -1.0


def test_create_collection_executes_inside_write_lock(test_settings) -> None:
    class TrackingLock:
        held = False

        def __enter__(self):
            self.held = True

        def __exit__(self, *_):
            self.held = False

    lock = TrackingLock()
    config = EmbeddingConfig.from_settings(test_settings)

    class Client:
        def create_collection(self, **kwargs):
            assert lock.held is True
            assert kwargs["configuration"] == {"hnsw": {"space": "cosine"}}
            assert kwargs["embedding_function"] is None
            return SimpleNamespace(
                name=kwargs["name"],
                metadata=kwargs["metadata"],
                configuration={
                    "hnsw": {"space": "cosine"},
                    "embedding_function": None,
                },
            )

    store = VectorStoreService(
        test_settings,
        write_lock=lock,  # type: ignore[arg-type]
        client=Client(),
    )
    name, generation = store.generate_collection_name(
        "kb", config.config_hash
    )

    store.create_collection(
        name=name,
        knowledge_base_id="kb",
        config=config,
        generation=generation,
    )


@pytest.mark.parametrize(
    ("role", "status", "for_write", "allowed"),
    [
        ("active", "ACTIVE", False, True),
        ("active", "ACTIVE", True, True),
        ("active", "RETIRED", False, True),
        ("active", "RETIRED", True, False),
        ("active", "BUILDING", False, False),
        ("active", "FAILED", False, False),
        ("previous", "RETIRED", False, True),
        ("previous", "ACTIVE", False, True),
        ("previous", "FAILED", False, False),
        ("building", "BUILDING", True, True),
        ("building", "FAILED", False, True),
        ("building", "FAILED", True, False),
        ("cleanup", "RETIRED", False, True),
        ("cleanup", "FAILED", False, True),
        ("cleanup", "ACTIVE", False, False),
    ],
)
def test_lifecycle_pointer_contract(
    role: str,
    status: str,
    for_write: bool,
    allowed: bool,
) -> None:
    collection = SimpleNamespace(
        name="collection",
        metadata={"lifecycle_status": status},
    )

    if allowed:
        VectorStoreService.validate_lifecycle(
            collection,
            role=role,  # type: ignore[arg-type]
            for_write=for_write,
        )
    else:
        with pytest.raises(VectorStoreException):
            VectorStoreService.validate_lifecycle(
                collection,
                role=role,  # type: ignore[arg-type]
                for_write=for_write,
            )

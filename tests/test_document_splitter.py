"""Configuration, metadata, and stable chunking tests."""

from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.core.exceptions import FileProcessException, ValidationException
from app.services.document_loader import DocumentLoaderService
from app.services.document_splitter import DocumentSplitterService
from tests.conftest import make_test_settings
from tests.test_document_loader import write_text_pdf


def source_document(content: str = "abcdefghij") -> Document:
    return Document(
        page_content=content,
        metadata={
            "file_id": "file-1",
            "knowledge_base_id": "kb-1",
            "file_name": "sample.txt",
            "file_type": ".txt",
            "source": "sample.txt",
            "source_index": 0,
            "custom": {"value": 1},
        },
    )


def test_splitter_reads_settings_and_keeps_explicit_compatibility(
    tmp_path: Path,
) -> None:
    settings = make_test_settings(tmp_path, CHUNK_SIZE=7, CHUNK_OVERLAP=3)
    configured = DocumentSplitterService(settings=settings)
    explicit = DocumentSplitterService(5, 2, settings=settings)

    assert (configured.chunk_size, configured.chunk_overlap) == (7, 3)
    assert (explicit.chunk_size, explicit.chunk_overlap) == (5, 2)


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [(0, 0), (5, -1), (5, 5), (True, 0), (5, False), ("5", 1)],
)
def test_splitter_rejects_invalid_configuration(
    chunk_size: object, chunk_overlap: object
) -> None:
    with pytest.raises(ValidationException):
        DocumentSplitterService(chunk_size, chunk_overlap)  # type: ignore[arg-type]


def test_character_chunks_overlap_metadata_and_ids_are_stable() -> None:
    splitter = DocumentSplitterService(5, 2)
    original = source_document()

    first = splitter.split_documents([original])
    second = splitter.split_documents([source_document()])

    assert [item.page_content for item in first] == ["abcde", "defgh", "ghij"]
    assert [item.metadata for item in first] == [item.metadata for item in second]
    assert [item.metadata["chunk_index"] for item in first] == [0, 1, 2]
    assert all(
        str(item.metadata["chunk_id"]).startswith("chunk_") for item in first
    )
    assert all(len(item.page_content) <= 5 for item in first)
    assert first[0].page_content[-2:] == first[1].page_content[:2]
    assert original.metadata.get("chunk_id") is None

    first[0].metadata["custom"]["value"] = 99
    assert first[1].metadata["custom"]["value"] == 1


def test_splitter_validates_documents_and_required_metadata() -> None:
    splitter = DocumentSplitterService(10, 2)
    with pytest.raises(ValidationException):
        splitter.split_documents([])
    with pytest.raises(FileProcessException):
        splitter.split_documents([source_document("   ")])

    missing = source_document()
    missing.metadata.pop("file_id")
    with pytest.raises(ValidationException, match="file_id"):
        splitter.split_documents([missing])

    invalid_index = source_document()
    invalid_index.metadata["source_index"] = -1
    with pytest.raises(ValidationException, match="source_index"):
        splitter.split_documents([invalid_index])


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        (".txt", "第一段\n\n第二段用于切分"),
        (".json", '[{"name":"一"},{"name":"二"}]'),
        (".csv", "name,value\n一,1\n二,2\n"),
    ],
)
def test_text_format_pipeline_is_reproducible(
    tmp_path: Path, suffix: str, content: str
) -> None:
    path = tmp_path / f"sample{suffix}"
    path.write_text(content, encoding="utf-8")
    loader = DocumentLoaderService()
    splitter = DocumentSplitterService(8, 2)

    def run() -> list[Document]:
        documents = loader.load_file(
            path,
            file_id="file-stable",
            knowledge_base_id="kb-stable",
        )
        return splitter.split_documents(documents)

    first = run()
    second = run()
    assert first
    assert all(item.page_content.strip() for item in first)
    assert {
        "file_id",
        "knowledge_base_id",
        "file_name",
        "file_type",
        "source",
        "source_index",
        "chunk_index",
        "chunk_id",
    }.issubset(first[0].metadata)
    assert [(item.page_content, item.metadata) for item in first] == [
        (item.page_content, item.metadata) for item in second
    ]


def test_pdf_pipeline_is_reproducible(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    write_text_pdf(path, ["Stable PDF text"])
    loader = DocumentLoaderService()
    splitter = DocumentSplitterService(8, 2)

    def run() -> list[Document]:
        return splitter.split_documents(
            loader.load_file(
                path,
                file_id="file-pdf",
                knowledge_base_id="kb-pdf",
            )
        )

    first = run()
    second = run()
    assert [item.metadata["page"] for item in first] == [1, 1, 1]
    assert [(item.page_content, item.metadata) for item in first] == [
        (item.page_content, item.metadata) for item in second
    ]

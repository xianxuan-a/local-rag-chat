"""Supported-format parsing and provenance tests."""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.exceptions import (
    FileProcessException,
    ResourceNotFoundException,
    UnsupportedFileTypeException,
    ValidationException,
)
from app.services.document_loader import DocumentLoaderService


FILE_ID = "11111111-1111-1111-1111-111111111111"
KNOWLEDGE_BASE_ID = "22222222-2222-2222-2222-222222222222"


def load(path: Path, **kwargs: Any) -> list[Document]:
    return DocumentLoaderService().load_file(
        path,
        file_id=FILE_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        **kwargs,
    )


def write_text_pdf(path: Path, pages: list[str | None]) -> None:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
        )
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)


def test_txt_utf8_cleaning_metadata_and_stability(tmp_path: Path) -> None:
    path = tmp_path / "知识.txt"
    path.write_text("\ufeff第一段\r\n\r\n第二段  内容", encoding="utf-8")

    first = load(
        path,
        additional_metadata={"tenant": "local", "file_id": "spoofed"},
    )
    second = load(path, additional_metadata={"tenant": "local"})

    assert first[0].page_content == "第一段\n\n第二段 内容"
    assert first[0].metadata == second[0].metadata
    assert first[0].metadata == {
        "tenant": "local",
        "file_id": FILE_ID,
        "knowledge_base_id": KNOWLEDGE_BASE_ID,
        "file_name": "知识.txt",
        "file_type": ".txt",
        "source": "知识.txt",
        "source_index": 0,
        "encoding": "utf-8-sig",
    }


def test_txt_gb18030_and_invalid_or_empty_content(tmp_path: Path) -> None:
    gb_path = tmp_path / "legacy.txt"
    gb_path.write_bytes("中文内容".encode("gb18030"))
    assert load(gb_path)[0].page_content == "中文内容"
    assert load(gb_path)[0].metadata["encoding"] == "gb18030"

    for name, content in (
        ("empty.txt", b""),
        ("blank.txt", b" \r\n\t"),
        ("invalid.txt", b"\x81"),
    ):
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(FileProcessException):
            load(path)


def test_json_object_array_order_unicode_and_failures(tmp_path: Path) -> None:
    object_path = tmp_path / "object.json"
    object_path.write_text('{"b":2,"a":"中文"}', encoding="utf-8")
    assert load(object_path)[0].page_content == '{"a":"中文","b":2}'

    array_path = tmp_path / "array.json"
    array_path.write_text('[{"z":1,"a":2},"值",3]', encoding="utf-8")
    first = load(array_path)
    second = load(array_path)
    assert [item.page_content for item in first] == [
        '{"a":2,"z":1}',
        '"值"',
        "3",
    ]
    assert [item.metadata for item in first] == [
        item.metadata for item in second
    ]
    assert [item.metadata["record_index"] for item in first] == [0, 1, 2]

    for name, content in (
        ("empty.json", ""),
        ("object-empty.json", "{}"),
        ("array-empty.json", "[]"),
        ("broken.json", '{"a":}'),
        ("duplicate.json", '{"a":1,"a":2}'),
        ("scalar.json", "42"),
    ):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        with pytest.raises(FileProcessException):
            load(path)


def test_csv_rows_headers_order_and_failures(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    path.write_bytes(
        "姓名,城市,备注\r\n张三,上海,\r\n\r\n李四,北京, 测试  内容 \r\n".encode(
            "utf-8"
        )
    )

    first = load(path)
    second = load(path)
    assert [item.page_content for item in first] == [
        "姓名: 张三\n城市: 上海\n备注:",
        "姓名: 李四\n城市: 北京\n备注: 测试 内容",
    ]
    assert [item.metadata["row"] for item in first] == [2, 4]
    assert [item.metadata for item in first] == [
        item.metadata for item in second
    ]

    invalid_cases = {
        "empty.csv": "",
        "header-only.csv": "a,b\n",
        "empty-header.csv": "a,\n1,2\n",
        "duplicate-header.csv": "a,a\n1,2\n",
        "columns.csv": "a,b\n1,2,3\n",
        "broken.csv": 'a,b\n"unterminated,2\n',
    }
    for name, content in invalid_cases.items():
        invalid_path = tmp_path / name
        invalid_path.write_text(content, encoding="utf-8")
        with pytest.raises(FileProcessException):
            load(invalid_path)


def test_pdf_pages_stability_blank_and_invalid_files(tmp_path: Path) -> None:
    path = tmp_path / "pages.pdf"
    write_text_pdf(path, ["First page", None, "Third page"])

    first = load(path)
    second = load(path)
    assert [item.page_content for item in first] == ["First page", "Third page"]
    assert [item.metadata["page"] for item in first] == [1, 3]
    assert all(item.metadata["total_pages"] == 3 for item in first)
    assert [item.metadata for item in first] == [
        item.metadata for item in second
    ]

    blank_path = tmp_path / "blank.pdf"
    write_text_pdf(blank_path, [None])
    with pytest.raises(FileProcessException, match="未提取到有效文本"):
        load(blank_path)

    encrypted_path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with encrypted_path.open("wb") as output:
        writer.write(output)
    with pytest.raises(FileProcessException, match="已加密"):
        load(encrypted_path)

    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"not a pdf")
    with pytest.raises(FileProcessException, match="损坏"):
        load(corrupt_path)


def test_loader_validates_path_type_identity_and_extension(tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFoundException):
        load(tmp_path / "missing.txt")

    unsupported = tmp_path / "sample.md"
    unsupported.write_text("content", encoding="utf-8")
    with pytest.raises(UnsupportedFileTypeException):
        load(unsupported)

    text_path = tmp_path / "sample.txt"
    text_path.write_text("content", encoding="utf-8")
    with pytest.raises(ValidationException):
        DocumentLoaderService().load_file(
            text_path,
            file_id="",
            knowledge_base_id=KNOWLEDGE_BASE_ID,
        )
    with pytest.raises(ValidationException, match="扩展名"):
        load(text_path, file_type="json")

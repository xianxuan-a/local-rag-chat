"""MD5 helper behavior."""

from pathlib import Path

from app.services.hash_service import HashService


def test_equal_content_has_equal_md5() -> None:
    assert HashService.calculate_bytes_md5(b"same") == HashService.calculate_text_md5(
        "same"
    )


def test_different_content_has_different_md5() -> None:
    assert HashService.calculate_bytes_md5(
        b"first"
    ) != HashService.calculate_bytes_md5(b"second")


def test_file_md5_matches_bytes_md5(tmp_path: Path) -> None:
    content = (b"chunked-content" * 200_000) + b"tail"
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(content)

    assert HashService.calculate_file_md5(
        file_path, chunk_size=1024
    ) == HashService.calculate_bytes_md5(content)

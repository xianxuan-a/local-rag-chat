"""Streaming MD5 helpers used for local file identity checks."""

from hashlib import md5
from pathlib import Path


class HashService:
    """Calculate deterministic MD5 values without loading whole files in memory."""

    DEFAULT_CHUNK_SIZE = 1024 * 1024

    @staticmethod
    def calculate_file_md5(
        file_path: str | Path,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> str:
        """Hash a file using bounded, repeated reads."""
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")

        digest = md5()
        with Path(file_path).open("rb") as file_handle:
            while chunk := file_handle.read(chunk_size):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def calculate_bytes_md5(content: bytes) -> str:
        """Hash an in-memory byte sequence."""
        return md5(content).hexdigest()

    @staticmethod
    def calculate_text_md5(content: str, encoding: str = "utf-8") -> str:
        """Encode and hash text deterministically."""
        return HashService.calculate_bytes_md5(content.encode(encoding))
